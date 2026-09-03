"""Format-fidelity eval for the extraction stage (``REQ-EXT-04``).

``extraction_fidelity_eval`` asks how well one format — PDF — survives extraction,
comparing PyMuPDF's several reading modes. This asks the question ingestion
breadth actually raises: **does a document lose anything by arriving in a
different container?** The pipeline now ingests PDF, DOCX, HTML and plain text,
and a new source is only worth having if the text that reaches the chunker is the
same text.

**One variable, four containers.** The same paragraphs are written into all four
formats and read back through the shipped seam
(``FileProcessing._extract_pages``), so the only thing that differs between arms
is the file format. PDF is the baseline every other arm is read against, because
it is the path the rest of the pipeline was measured on.

====================  ==========================================  ================
arm                   what it reads                               expectation
====================  ==========================================  ================
``pdf``               the baseline: real pages, laid out with     high recall,
                      PyMuPDF                                     3 pages
``docx``              a Word package, walked in document order    ~1.0, 1 page
``html``              markup with a head, styles and a script     ~1.0, 1 page
``text``              the bytes themselves                        1.0, 1 page
``html_undressed``    control: the HTML bytes decoded as plain    recall holds,
                      text, markup left in                        precision falls
``text_shuffled``     control: the text arm, words shuffled       recall holds,
                                                                  order falls
====================  ==========================================  ================

**The two controls are not candidates.** They exist so the numbers are readable:
``html_undressed`` keeps every word of the prose and adds the tags, CSS and
JavaScript around it, so it must hold recall and lose precision — which is what
shows precision is measuring the markup handling and not the text. ``text_shuffled``
keeps every word and destroys only their order, so it must hold recall and lose
order fidelity. If either control scored like its candidate, neither metric would
be telling us anything.

**Pagination is reported, not scored.** Only a PDF stores page boundaries; DOCX,
HTML and text leave pagination to whatever renders them, so they extract to one
page by design (see :mod:`services.extraction.base`). ``pages_extracted`` records
the difference rather than penalising it — that collapse *is* the graceful
degradation the requirement asks for, and scoring per page would punish the three
formats for a page structure their sources never had.

**Chunk shape is the second half.** Text that survives extraction but chunks into
something unusable is no good either, so each arm's pages are run through the two
deterministic chunkers (fixed-size and structural) and their shape reported next
to the fidelity numbers. The semantic strategy is left out on purpose: it embeds,
which would put an Ollama server between this eval and its result, and what it
adds here — whether boundaries land on topic shifts — is the chunking eval's
question, asked on this same corpus.

**The documents are generated, never committed.** Source documents are not checked
in (see CLAUDE.md), so every container is built at run time from the existing
``.txt`` fixtures, and the paragraphs that went in are kept as ground truth — which
is what makes fidelity exactly measurable rather than eyeballed.

Extraction is deterministic and the one shuffle is seeded, so these digits
reproduce run to run against the same PyMuPDF, python-docx and BeautifulSoup.

Run it with:
    uv run python -m evals.extraction_formats_eval

It needs neither Ollama nor a database. Results are written to
``evals/results/extraction_formats.json`` and are a regenerable artifact, not a
one-off screenshot.
"""

import json
import random
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document

from dtos.requests import FixedSizeChunkingRequest
from dtos.responses import DocType
from evals.extraction_fidelity_eval import _build_pdf, _fidelity, _paginate, _words
from evals.fixed_size_chunking_eval import _load_pages, chunk_metrics
from services.chunking import FixedSizeChunker, StructuralChunker
from services.file_processing import FileProcessing

_DATA_DIR = Path(__file__).parent / "data"
_RESULTS_PATH = Path(__file__).parent / "results" / "extraction_formats.json"

# The same two fixtures every other eval uses, so all of them talk about one
# corpus: flat prose first, then a document that marks up its own structure.
_DATASETS = [_DATA_DIR / "sample.txt", _DATA_DIR / "structured_sample.txt"]

# Pages to lay the PDF arm out across. The other three formats have no page
# breaks to lay anything across -- that asymmetry is the point of the arm.
_PAGE_COUNT = 3

# Words per chunk for the shape comparison. Small enough that a short fixture
# still produces several chunks to have a distribution.
_CHUNK_SIZE = 128

# Fixed so the control arm's shuffle is the same one on every run.
_SEED = 20260903

# The two arms that exist to show the metrics separate, and the four that are
# real candidates. Every arm is scored identically; only the reading differs.
_CONTROLS = ("html_undressed", "text_shuffled")
_ARMS = ("pdf", "docx", "html", "text", *_CONTROLS)

# Non-content the HTML arm carries, so the arm is scored against markup a real
# page ships rather than a bare <p> per paragraph. Every word here must be
# *absent* from the extraction: none of it is shown to a reader. Deliberately no
# navigation or footer text -- that would be visible content, and every arm has
# to carry the same visible words for the comparison to mean anything.
_HTML_TITLE = "Corporate Handbook — Internal"
_HTML_STYLE = "body { font-family: Georgia, serif; } .prose p { margin: 0 0 1em; }"
_HTML_SCRIPT = "var analytics = { id: 42 }; window.addEventListener('load', track);"


def _blocks(pages: list[str]) -> list[str]:
    """The document's paragraphs in order, whatever pages they were laid on.

    This is the ground truth every arm is scored against: the same words, in the
    same order, before any container has touched them.
    """
    return [
        block.strip() for page in pages for block in page.split("\n\n") if block.strip()
    ]


def _build_docx(blocks: list[str]) -> bytes:
    """Write ``blocks`` as the paragraphs of a Word package."""
    document = Document()
    for block in blocks:
        document.add_paragraph(block)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_html(blocks: list[str]) -> bytes:
    """Write ``blocks`` as the prose of an HTML page, with real page chrome.

    The head, stylesheet and script carry words no reader ever sees. Keeping them
    in is what gives the ``html`` arm something to strip and the
    ``html_undressed`` control something to fail on.
    """
    paragraphs = "\n".join(f"    <p>{block}</p>" for block in blocks)
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'  <meta charset="utf-8">\n  <title>{_HTML_TITLE}</title>\n'
        f"  <style>{_HTML_STYLE}</style>\n</head>\n<body>\n"
        f'  <script>{_HTML_SCRIPT}</script>\n  <div class="prose">\n'
        f"{paragraphs}\n  </div>\n</body>\n</html>\n"
    ).encode("utf-8")


def _build_text(blocks: list[str]) -> bytes:
    """Write ``blocks`` as a plain-text file, one blank line between each."""
    return "\n\n".join(blocks).encode("utf-8")


def _extract(arm: str, documents: dict[str, bytes], rng: random.Random) -> list[str]:
    """Read one arm's document back, through the seam ``/process`` uses."""
    if arm in ("pdf", "docx", "html", "text"):
        return FileProcessing._extract_pages(documents[arm], DocType(arm))
    if arm == "html_undressed":
        # The control: the same bytes, read as if the markup were prose.
        return FileProcessing._extract_pages(documents["html"], DocType.text)
    if arm == "text_shuffled":
        pages = FileProcessing._extract_pages(documents["text"], DocType.text)
        shuffled = []
        for page in pages:
            words = _words(page)
            rng.shuffle(words)
            shuffled.append(" ".join(words))
        return shuffled
    raise ValueError(f"unknown extraction arm: {arm}")


def _chunk_shape(pages: list[str]) -> dict[str, Any]:
    """Shape of the chunks each deterministic strategy makes of ``pages``.

    Text that survives extraction and then chunks into one huge block, or into
    hundreds of fragments, is not usable text — so the container is scored on what
    the chunker makes of it, not only on the words it gave back.
    """
    fixed = FixedSizeChunker(FixedSizeChunkingRequest(chunk_size=_CHUNK_SIZE)).chunk(
        pages
    )
    structural = StructuralChunker().chunk(pages)
    return {
        "fixed": chunk_metrics(fixed, _CHUNK_SIZE),
        "structural": chunk_metrics(structural),
    }


def _score_arm(truth: list[str], pages: list[str]) -> dict[str, Any]:
    """Score one arm's extraction against the words that were written into it.

    Scored on the flattened word sequence rather than page by page: three of the
    four formats have exactly one page, so a per-page comparison would measure
    the formats' pagination instead of their fidelity.
    """
    extracted = [word for page in pages for word in _words(page)]
    return {
        "pages_extracted": len(pages),
        "paginated": len(pages) > 1,
        "words_extracted": len(extracted),
        **_fidelity(truth, extracted),
        "chunks": _chunk_shape(pages),
    }


def _run_dataset(path: Path, rng: random.Random) -> dict[str, Any]:
    """Write one fixture into every container and read them all back."""
    laid_out = _paginate(_load_pages(path), _PAGE_COUNT)
    blocks = _blocks(laid_out)
    truth = _words(" ".join(blocks))

    pdf, font_size = _build_pdf(laid_out, "single_column")
    documents = {
        "pdf": pdf,
        "docx": _build_docx(blocks),
        "html": _build_html(blocks),
        "text": _build_text(blocks),
    }
    return {
        "dataset": path.name,
        "document_words": len(truth),
        "blocks": len(blocks),
        "pdf_pages": _PAGE_COUNT,
        "pdf_font_size": font_size,
        "arms": [
            {
                "arm": arm,
                "role": "control" if arm in _CONTROLS else "candidate",
                "bytes": len(documents.get(arm, documents["text"])),
                **_score_arm(truth, _extract(arm, documents, rng)),
            }
            for arm in _ARMS
        ],
    }


def _run() -> dict[str, Any]:
    rng = random.Random(_SEED)
    return {
        "baseline": "pdf",
        "chunk_size": _CHUNK_SIZE,
        "seed": _SEED,
        "datasets": [_run_dataset(path, rng) for path in _DATASETS],
    }


def _print_table(payload: dict[str, Any]) -> None:
    header = (
        f"{'arm':<16} {'role':<10} {'pages':>6} {'words':>7} {'recall':>7} "
        f"{'prec':>7} {'order':>7} {'fixed':>7} {'struct':>7}"
    )
    for dataset in payload["datasets"]:
        print(
            f"\nextraction formats - {dataset['dataset']} "
            f"({dataset['document_words']} words in {dataset['blocks']} paragraphs, "
            f"chunk size {payload['chunk_size']})"
        )
        print(header)
        print("-" * len(header))
        for arm in dataset["arms"]:
            print(
                f"{arm['arm']:<16} {arm['role']:<10} {arm['pages_extracted']:>6} "
                f"{arm['words_extracted']:>7} {arm['recall']:>7.3f} "
                f"{arm['precision']:>7.3f} {arm['order_fidelity']:>7.3f} "
                f"{arm['chunks']['fixed']['num_chunks']:>7} "
                f"{arm['chunks']['structural']['num_chunks']:>7}"
            )


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
