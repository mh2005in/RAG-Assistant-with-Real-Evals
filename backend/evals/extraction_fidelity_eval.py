"""Extraction-fidelity eval for the extraction stage (``REQ-EVL-02``).

Every other eval in this directory starts from a ``.txt`` fixture, which skips the
stage that turns a binary PDF into text. That stage makes two quality claims worth
measuring: the text that comes out is the text that went in, and each page's text
comes back attributed to *that* page — the promise every citation downstream rests
on.

**The comparison is the point.** A fidelity number on its own says nothing, so the
same generated PDF is extracted several ways and scored identically:

====================  ==========================================  ================
arm                   what it extracts with                       expectation
====================  ==========================================  ================
``shipped``           ``FileProcessing._extract_pages`` —         highest
                      PyMuPDF's default ``get_text()``
``blocks``            ``get_text("blocks")``, block order kept    close to shipped
``words``             ``get_text("words")``, word order kept      close to shipped
``sorted``            ``get_text("text", sort=True)`` —           layout-dependent
                      geometric top-down, left-to-right
``shuffled``          the shipped extraction, words shuffled      control
====================  ==========================================  ================

``shuffled`` is a control, not a candidate: it keeps every word and destroys only
the order, so it must score 1.0 on recall and far lower on order fidelity. If it
did not, the two metrics would not be measuring different things and neither
number would be readable.

**The PDFs are generated, never committed.** Source documents are not checked in
(see CLAUDE.md), so the eval lays the existing ``.txt`` fixtures out into a PDF
with PyMuPDF at run time and keeps the words it laid out as ground truth — which
is what makes fidelity exactly measurable rather than eyeballed. Two layouts,
because they stress different things:

* ``single_column`` — one text column per page; the easy case.
* ``two_column`` — the same words in two columns. Reading order is now a choice
  rather than a given, and an extractor that reads across the page instead of down
  the column scrambles it while losing no text at all.

The flat fixture carries no page breaks, so the eval paginates it itself: page
attribution can only be wrong when there is more than one page to be wrong about.

Extraction is deterministic. Unlike the generation eval, these digits are
reproducible run to run against the same PyMuPDF.

Run it with:
    uv run python -m evals.extraction_fidelity_eval

It needs neither Ollama nor a database. Results are written to
``evals/results/extraction_fidelity.json`` and are a regenerable artifact, not a
one-off screenshot.
"""

import json
import random
import statistics
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pymupdf

from dtos.requests import PageExclusion
from dtos.responses import DocType
from evals.fixed_size_chunking_eval import _load_pages
from services.file_processing import FileProcessing

_DATA_DIR = Path(__file__).parent / "data"
_RESULTS_PATH = Path(__file__).parent / "results" / "extraction_fidelity.json"

# Flat prose first, then a document that marks up its own structure -- the same
# two fixtures the other evals use, so every eval talks about one corpus.
_DATASETS = [_DATA_DIR / "sample.txt", _DATA_DIR / "structured_sample.txt"]

# Pages to lay each fixture out across. More than one, so a word can land on the
# wrong page and be counted against it.
_PAGE_COUNT = 3

# A4 in points, with a margin wide enough that no glyph sits on the crop edge.
_PAGE_WIDTH = 595.0
_PAGE_HEIGHT = 842.0
_MARGIN = 50.0
# Gutter between the two columns of the two-column layout.
_GUTTER = 20.0

# Tried largest-first; the first size whose text fits every box is used, so a
# longer page shrinks rather than silently losing its overflow.
_FONT_SIZES = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0]
_FONT = "helv"

_LAYOUTS = ["single_column", "two_column"]
_ARMS = ["shipped", "blocks", "words", "sorted", "shuffled"]

# Fixed so the control arm's shuffle is the same one on every run.
_SEED = 20260902

# Page excluded in the round-trip check. Page 2 is the interior one: dropping it
# is what would shift page 3's number if exclusion removed pages instead of
# blanking them.
_EXCLUDED_PAGE = 2


def _words(text: str) -> list[str]:
    """Whitespace-split words, the unit both chunking and these metrics count."""
    return text.split()


def _paginate(pages: list[str], page_count: int) -> list[str]:
    """Lay a fixture out across ``page_count`` pages, splitting on paragraphs.

    The fixtures are single-page (no form feed), so the eval chooses the page
    breaks. Paragraphs are kept whole and distributed to keep the pages close to
    equal in words; intra-paragraph line breaks are collapsed, since the PDF
    re-wraps the text anyway and the ground truth has to be what was laid out.
    """
    paragraphs = [
        " ".join(block.split())
        for page in pages
        for block in page.split("\n\n")
        if block.strip()
    ]
    target = sum(len(_words(block)) for block in paragraphs) / page_count

    laid_out: list[list[str]] = [[] for _ in range(page_count)]
    index = 0
    for paragraph in paragraphs:
        # Move on once this page has its share, but never past the last page --
        # the remainder always has somewhere to go.
        while (
            index < page_count - 1
            and sum(len(_words(block)) for block in laid_out[index]) >= target
        ):
            index += 1
        laid_out[index].append(paragraph)
    return ["\n\n".join(blocks) for blocks in laid_out]


def _boxes(layout: str) -> list[Any]:
    """The text boxes of one page, in reading order."""
    top, bottom = _MARGIN, _PAGE_HEIGHT - _MARGIN
    left, right = _MARGIN, _PAGE_WIDTH - _MARGIN
    if layout == "single_column":
        return [pymupdf.Rect(left, top, right, bottom)]
    middle = (left + right) / 2
    return [
        pymupdf.Rect(left, top, middle - _GUTTER / 2, bottom),
        pymupdf.Rect(middle + _GUTTER / 2, top, right, bottom),
    ]


def _split_for_boxes(text: str, box_count: int) -> list[str]:
    """Split a page's text into one run of words per box, in reading order."""
    if box_count == 1:
        return [text]
    words = _words(text)
    per_box = len(words) // box_count + 1
    return [
        " ".join(words[start : start + per_box])
        for start in range(0, box_count * per_box, per_box)
    ][:box_count]


def _build_pdf(pages: list[str], layout: str) -> tuple[bytes, float]:
    """Render ``pages`` as a PDF in ``layout``, returning the bytes and font size.

    The font size is the largest of ``_FONT_SIZES`` at which every box holds all
    of its text: ``insert_textbox`` returns the unused vertical space, so a
    negative return means the text overflowed and would have been silently cut.
    Recording the size that was used keeps the artifact self-describing. The PDF's
    byte length is deliberately *not* recorded: it moves by a byte or two between
    runs of the same input, which would put a spurious diff in an artifact whose
    whole point is that a re-run reproduces it.
    """
    for font_size in _FONT_SIZES:
        document = pymupdf.open()
        fits = True
        for text in pages:
            page = document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
            boxes = _boxes(layout)
            for box, part in zip(boxes, _split_for_boxes(text, len(boxes))):
                overflow = page.insert_textbox(
                    box, part, fontsize=font_size, fontname=_FONT
                )
                if overflow < 0:
                    fits = False
                    break
            if not fits:
                break
        if fits:
            content: bytes = document.tobytes()
            document.close()
            return content, font_size
        document.close()
    raise RuntimeError(
        f"no font size in {_FONT_SIZES} fits the {layout} layout; "
        "shorten the page or widen the box"
    )


def _extract(content: bytes, arm: str, rng: random.Random) -> list[str]:
    """Extract one PDF's pages with the strategy named by ``arm``."""
    if arm in ("shipped", "shuffled"):
        # The shipped extractor, reached one level in: process() returns chunk
        # counts, and this eval needs the page text it extracted on the way.
        pages = FileProcessing._extract_pages(content, DocType.pdf)
        if arm == "shipped":
            return pages
        shuffled = []
        for page in pages:
            words = _words(page)
            rng.shuffle(words)
            shuffled.append(" ".join(words))
        return shuffled

    with pymupdf.open(stream=content, filetype="pdf") as document:
        if arm == "sorted":
            return [page.get_text("text", sort=True) for page in document]
        if arm == "blocks":
            # (x0, y0, x1, y1, text, block_no, block_type); type 0 is text.
            return [
                " ".join(block[4] for block in page.get_text("blocks") if block[6] == 0)
                for page in document
            ]
        if arm == "words":
            # (x0, y0, x1, y1, word, block_no, line_no, word_no).
            return [
                " ".join(word[4] for word in page.get_text("words"))
                for page in document
            ]
    raise ValueError(f"unknown extraction arm: {arm}")


def _fidelity(truth: list[str], extracted: list[str]) -> dict[str, float]:
    """Score one extracted word sequence against the words that were laid out.

    ``recall`` and ``precision`` are multiset overlap — they see *which* words
    survived and how many spurious ones appeared, and are blind to order.
    ``order_fidelity`` is the longest-common-subsequence ratio over the sequences,
    which sees only order. Kept apart deliberately: text can be complete and
    scrambled, or ordered and lossy, and one number cannot say which happened.
    """
    if not truth:
        return {"recall": 0.0, "precision": 0.0, "order_fidelity": 0.0}
    overlap = sum((Counter(truth) & Counter(extracted)).values())
    return {
        "recall": round(overlap / len(truth), 4),
        "precision": round(overlap / len(extracted), 4) if extracted else 0.0,
        "order_fidelity": round(
            SequenceMatcher(None, truth, extracted, autojunk=False).ratio(), 4
        ),
    }


def _score_arm(truth_pages: list[str], extracted_pages: list[str]) -> dict[str, Any]:
    """Per-page fidelity, averaged, plus the document-level recall.

    The per-page means are the headline: a word recovered onto the *wrong* page
    counts against the page it belonged to, so page attribution is folded in.
    ``document_recall`` scores the same words with the page boundaries removed,
    which is what separates the two failure modes — text lost outright (both fall)
    from text recovered onto the wrong page (only the per-page mean falls).
    """
    truth_words = [_words(page) for page in truth_pages]
    got_words = [_words(page) for page in extracted_pages]
    # A missing page still has to be scored, or losing one would look like a
    # shorter document rather than a failure.
    got_words += [[] for _ in range(len(truth_words) - len(got_words))]

    per_page = [_fidelity(truth, got) for truth, got in zip(truth_words, got_words)]
    flat_truth = [word for page in truth_words for word in page]
    flat_got = [word for page in got_words for word in page]
    return {
        "pages_extracted": len(extracted_pages),
        "words_extracted": len(flat_got),
        "page_recall": round(statistics.fmean(row["recall"] for row in per_page), 4),
        "page_precision": round(
            statistics.fmean(row["precision"] for row in per_page), 4
        ),
        "order_fidelity": round(
            statistics.fmean(row["order_fidelity"] for row in per_page), 4
        ),
        "document_recall": _fidelity(flat_truth, flat_got)["recall"],
    }


def _exclusion_round_trip(truth_pages: list[str], content: bytes) -> dict[str, Any]:
    """Does page exclusion still hold after a real PDF round trip?

    ``REQ-EXT-02`` blanks an excluded page rather than dropping it, so the pages
    after it keep their numbers. The unit tests prove that over a list of strings;
    this proves it over text that has actually been through a PDF, which is the
    only place the page boundaries are real. ``kept_recall`` is the share of the
    surviving pages' words still present, and ``leaked_words`` counts words unique
    to the excluded page that survived anyway — it must be 0.
    """
    extracted = FileProcessing._extract_pages(content, DocType.pdf)
    kept = FileProcessing._exclude_pages(
        extracted, PageExclusion(exclude_pages=[_EXCLUDED_PAGE])
    )
    surviving = [
        word
        for number, page in enumerate(truth_pages, start=1)
        if number != _EXCLUDED_PAGE
        for word in _words(page)
    ]
    excluded_only = set(_words(truth_pages[_EXCLUDED_PAGE - 1])) - set(surviving)
    kept_words = [word for page in kept for word in _words(page)]
    return {
        "excluded_page": _EXCLUDED_PAGE,
        "pages_after_exclusion": len(kept),
        "page_numbering_preserved": len(kept) == len(extracted),
        "kept_recall": _fidelity(surviving, kept_words)["recall"],
        "leaked_words": sum(1 for word in kept_words if word in excluded_only),
    }


def _run_dataset(path: Path, rng: random.Random) -> dict[str, Any]:
    """Lay one fixture out in every layout and extract it every way."""
    truth_pages = _paginate(_load_pages(path), _PAGE_COUNT)
    layouts = []
    for layout in _LAYOUTS:
        content, font_size = _build_pdf(truth_pages, layout)
        layouts.append(
            {
                "layout": layout,
                "font_size": font_size,
                "arms": [
                    {"arm": arm, **_score_arm(truth_pages, _extract(content, arm, rng))}
                    for arm in _ARMS
                ],
                "page_exclusion": _exclusion_round_trip(truth_pages, content),
            }
        )
    return {
        "dataset": path.name,
        "pages": _PAGE_COUNT,
        "document_words": sum(len(_words(page)) for page in truth_pages),
        "words_per_page": [len(_words(page)) for page in truth_pages],
        "layouts": layouts,
    }


def _run() -> dict[str, Any]:
    rng = random.Random(_SEED)
    return {
        "extractor": "pymupdf",
        "pymupdf_version": pymupdf.version[0],
        "seed": _SEED,
        "datasets": [_run_dataset(path, rng) for path in _DATASETS],
    }


def _print_table(payload: dict[str, Any]) -> None:
    header = (
        f"{'arm':<10} {'pages':>6} {'words':>7} {'recall':>7} {'prec':>7} "
        f"{'order':>7} {'doc_rec':>8}"
    )
    for dataset in payload["datasets"]:
        for layout in dataset["layouts"]:
            print(
                f"\nextraction fidelity - {dataset['dataset']} / {layout['layout']} "
                f"({dataset['document_words']} words over {dataset['pages']} pages, "
                f"{layout['font_size']}pt)"
            )
            print(header)
            print("-" * len(header))
            for arm in layout["arms"]:
                print(
                    f"{arm['arm']:<10} {arm['pages_extracted']:>6} "
                    f"{arm['words_extracted']:>7} {arm['page_recall']:>7.3f} "
                    f"{arm['page_precision']:>7.3f} {arm['order_fidelity']:>7.3f} "
                    f"{arm['document_recall']:>8.3f}"
                )
            exclusion = layout["page_exclusion"]
            print(
                f"page exclusion: page {exclusion['excluded_page']} blanked, "
                f"{exclusion['pages_after_exclusion']} pages kept, "
                f"numbering preserved {exclusion['page_numbering_preserved']}, "
                f"kept_recall {exclusion['kept_recall']:.3f}, "
                f"leaked {exclusion['leaked_words']}"
            )


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
