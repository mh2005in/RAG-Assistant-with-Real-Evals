"""Answer-faithfulness eval for the generation stage (``REQ-EVL-06``).

The chunking evals measure how a document is cut up. This one measures what the
model does with what it retrieves: given the numbered, cited context ``/answer``
builds, is the generated answer actually grounded in it?

**The comparison is the point.** A faithfulness number on its own says nothing —
if the metric cannot tell a grounded answer from an ungrounded one, it is not
measuring grounding. So every question is answered three ways, changing only what
the generator is shown, and **all three are scored against the same context**: the
chunks retrieved for that question.

====================  ============================================  ============
condition             what the generator is given                   expectation
====================  ============================================  ============
``grounded``          the top-k chunks retrieved for the question    highest
``distractor``        the *bottom*-k — the least similar chunks      below grounded
``closed_book``       no context at all                             below grounded
====================  ============================================  ============

Only the gap between ``grounded`` and the two controls is a claim. The controls
do **not** hold a stable order against each other — measured, not assumed: across
datasets and across runs, ``distractor`` and ``closed_book`` have each scored
above the other. Both are ungrounded in different ways and the metric does not
reliably rank one kind of ungroundedness against another at this sample size, so
**grounded above both** is the ordering that says the metric works, and nothing
should be read into which control came second.

``closed_book`` is a control, not a code path: :class:`~services.answering.Answering`
never generates without context — it returns a fixed "no documents" answer instead.
Here the model is asked the question bare, so the score shows what an answer written
from parametric memory scores against context it never saw. ``distractor`` is the
adversarial arm: the model is given real, fluent, *wrong* material, which is the
case a citation-blind metric is most likely to wave through. Taking it from the
bottom of the same ranking keeps it disjoint from the grounded context by
construction.

Retrieval is done in-process (embed the chunks, embed the question, take the top-k
by cosine) rather than through Postgres, mirroring the ranking
:meth:`~services.storage.postgres.PostgresStorage.search_chunks` performs in SQL.
That keeps the eval offline and DB-free — it needs only a running Ollama, for the
embeddings and the generation.

Generation is seeded, which narrows the run-to-run spread but — measured, not
assumed — does **not** make it bit-identical: two runs of this eval produced the
same answers, a third did not, and the flat dataset's summary moved by up to 0.33
on ``faithfulness``. Read a single run as one sample. What has held across every
run is the *ordering* (grounded above distractor on both support metrics, on both
datasets), and that ordering is the finding — not the digits. The prompt is the
shipped one (:meth:`~services.answering.Answering.build_prompt`), so this measures
the system's real behaviour and not a copy of it.

Run it with:
    OLLAMA_BASE_URL=http://localhost:11434 uv run python -m evals.answer_faithfulness_eval

Results are written to ``evals/results/answer_faithfulness.json`` and are a
regenerable artifact, not a one-off screenshot.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np

from dtos.requests import FixedSizeChunkingRequest
from dtos.responses import RetrievedChunk
from evals.fixed_size_chunking_eval import _load_pages
from services.answering import Answering
from services.chunking import FixedSizeChunker
from services.embedding import Embedder, OllamaEmbedder
from services.generation import (
    SUPPORT_THRESHOLD,
    LLMClient,
    OllamaClient,
    score_answer,
)

_DATA_DIR = Path(__file__).parent / "data"
_QUESTIONS_PATH = _DATA_DIR / "faithfulness_questions.json"
_RESULTS_PATH = Path(__file__).parent / "results" / "answer_faithfulness.json"

# Flat prose first, then a document that marks up its own structure -- the same
# two datasets the chunking comparison uses, so the evals talk about one corpus.
_DATASETS = [_DATA_DIR / "sample.txt", _DATA_DIR / "structured_sample.txt"]

# Retrieval context for every arm. Fixed-size is the structure-blind baseline, so
# no arm is flattered by a chunking strategy that happens to suit its dataset;
# which strategy retrieves best is REQ-EVL-01/REQ-EVL-03's question, not this one.
# The window is small and k is smaller: the samples are short documents, and at
# 128 words with k=3 the flat one held only three chunks, so "top 3" retrieved the
# whole document and there was nothing for retrieval -- or a distractor -- to do.
_CHUNK_SIZE = 64
_TOP_K = 2

# Pinned to narrow run-to-run spread. It does not make generation bit-identical
# (see the module docstring) -- the ordering between conditions is the result.
_SEED = 20260828

_CONDITIONS = ["grounded", "distractor", "closed_book"]

# Candidate support thresholds swept on every run, so the one the metric ships
# with stays answerable from the artifact rather than taken on trust.
_SWEEP_THRESHOLDS = [0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85]

# The control prompt: same question, no context to ground on. Deliberately not
# built by ``Answering`` -- the service never generates without context.
_CLOSED_BOOK_PROMPT = "Answer the question.\n\nQuestion: {query}\nAnswer:"

# Averaged across questions for the summary table. ``claims`` is carried along
# because an abstention scores as unsupported, so a condition's score is only
# readable next to how much it actually said.
_METRICS = [
    "faithfulness",
    "mean_support",
    "citation_coverage",
    "citation_validity",
    "cited_support",
    "claims",
]


def _as_chunks(texts: list[str], document: str) -> list[RetrievedChunk]:
    """Wrap chunk text as retrieval results so the shipped prompt can cite them.

    Page numbers are not modelled by the file-backed datasets, so every chunk
    reports page 1; the prompt's citation index is what the metric reads.
    """
    return [
        RetrievedChunk(
            document_id=0,
            document_name=document,
            chunking_strategy="fixed",
            chunk_index=index,
            page_number=1,
            text=text,
            score=0.0,
        )
        for index, text in enumerate(texts)
    ]


def _rank(question_vector: list[float], chunk_vectors: list[list[float]]) -> list[int]:
    """Every chunk index ranked by similarity to the question, best first."""
    vectors = np.asarray(chunk_vectors, dtype=float)
    query = np.asarray(question_vector, dtype=float)
    denom = np.linalg.norm(vectors, axis=1) * float(np.linalg.norm(query))
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = np.where(denom > 0, (vectors @ query) / denom, 0.0)
    return [int(index) for index in np.argsort(-sims)]


def _prompt(condition: str, question: str, context: list[RetrievedChunk]) -> str:
    """The prompt for one arm: the shipped one, or the no-context control."""
    if condition == "closed_book":
        return _CLOSED_BOOK_PROMPT.format(query=question)
    return Answering.build_prompt(question, context)


def _run_dataset(
    path: Path, embedder: Embedder, llm: LLMClient
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Answer every question three ways and score all three against its context."""
    pages = _load_pages(path)
    chunk_texts = FixedSizeChunker(
        FixedSizeChunkingRequest(chunk_size=_CHUNK_SIZE)
    ).chunk(pages)
    chunk_vectors = embedder.embed(chunk_texts)

    questions = json.loads(_QUESTIONS_PATH.read_text(encoding="utf-8"))[path.name]
    question_vectors = embedder.embed(questions)
    rankings = [_rank(vector, chunk_vectors) for vector in question_vectors]

    rows: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        ranking = rankings[index]
        context = _as_chunks([chunk_texts[i] for i in ranking[:_TOP_K]], path.name)
        # The distractor arm gets the *least* similar chunks instead. Taking them
        # from the same ranking guarantees they are disjoint from the grounded
        # context (the pool holds more than 2 * top_k chunks) -- an earlier version
        # handed it another question's top-k, which on the short document was the
        # same chunks in a different order, so the arm measured nothing.
        shown = {
            "grounded": context,
            "distractor": _as_chunks(
                [chunk_texts[i] for i in ranking[-_TOP_K:]], path.name
            ),
            "closed_book": [],
        }
        for condition in _CONDITIONS:
            answer = llm.generate(_prompt(condition, question, shown[condition]))
            # Scored against the question's own context in every arm, so the only
            # thing that varies between them is what the generator was shown.
            score = score_answer(answer, [chunk.text for chunk in context], embedder)
            rows.append(
                {
                    "question": question,
                    "condition": condition,
                    "answer": answer,
                    # Per-claim detail is kept: the summary means hide which claim
                    # drifted, and the support distribution is what the threshold
                    # was calibrated against.
                    **score.model_dump(),
                }
            )

    return {
        "dataset": path.name,
        "document_words": sum(len(page.split()) for page in pages),
        "chunks": len(chunk_texts),
        "questions": len(questions),
        "conditions": _summarise(rows),
    }, rows


def _threshold_sweep(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Supported-rate per condition at each candidate support threshold.

    The threshold in :mod:`services.generation.faithfulness` was chosen from this
    sweep, so it is recomputed on every run: if a different embedding model or a
    bigger question set moves the separation, the artifact says so instead of
    leaving a magic number behind to be trusted on faith. ``gap`` (grounded minus
    distractor) is reported as a check, not as the objective: the cut is chosen as
    the highest one that still accepts essentially every grounded claim, because a
    threshold can widen the gap purely by rejecting real grounding.
    """
    supports: dict[str, list[float]] = {condition: [] for condition in _CONDITIONS}
    for dataset in answers:
        for row in dataset["runs"]:
            supports[row["condition"]].extend(
                claim["support"] for claim in row["supports"]
            )

    sweep = []
    for threshold in _SWEEP_THRESHOLDS:
        rates = {
            condition: (
                round(sum(1 for x in values if x >= threshold) / len(values), 4)
                if values
                else None
            )
            for condition, values in supports.items()
        }
        grounded, distractor = rates["grounded"], rates["distractor"]
        sweep.append(
            {
                "threshold": threshold,
                **rates,
                "gap": (
                    round(grounded - distractor, 4)
                    if grounded is not None and distractor is not None
                    else None
                ),
            }
        )
    return sweep


def _summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mean each metric per condition, skipping the rows where it is undefined."""
    summary = []
    for condition in _CONDITIONS:
        matching = [row for row in rows if row["condition"] == condition]
        means: dict[str, Any] = {"condition": condition}
        for metric in _METRICS:
            values = [float(row[metric]) for row in matching if row[metric] is not None]
            means[metric] = round(sum(values) / len(values), 4) if values else None
        summary.append(means)
    return summary


def _run() -> dict[str, Any]:
    embedder = OllamaEmbedder.from_env()
    llm = OllamaClient.from_env(seed=_SEED)

    datasets = []
    answers = []
    for path in _DATASETS:
        summary, rows = _run_dataset(path, embedder, llm)
        datasets.append(summary)
        answers.append({"dataset": path.name, "runs": rows})

    return {
        "embedding_model": embedder._model,
        "generation_model": llm._model,
        "seed": _SEED,
        "chunking": {"strategy": "fixed", "chunk_size": _CHUNK_SIZE},
        "top_k": _TOP_K,
        "support_threshold": SUPPORT_THRESHOLD,
        "datasets": datasets,
        "threshold_sweep": _threshold_sweep(answers),
        "answers": answers,
    }


def _print_table(payload: dict[str, Any]) -> None:
    header = (
        f"{'condition':<12} {'faithful':>9} {'support':>8} {'cite_cov':>9} "
        f"{'cite_val':>9} {'cite_sup':>9} {'claims':>7}"
    )
    for dataset in payload["datasets"]:
        print(
            f"\nanswer faithfulness - {dataset['dataset']} "
            f"({dataset['questions']} questions over {dataset['chunks']} chunks, "
            f"generation: {payload['generation_model']})"
        )
        print(header)
        print("-" * len(header))
        for row in dataset["conditions"]:
            values = " ".join(
                f"{'-' if row[metric] is None else row[metric]:>9}"
                for metric in _METRICS[:-1]
            )
            print(f"{row['condition']:<12} {values} {row['claims']:>7}")


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
