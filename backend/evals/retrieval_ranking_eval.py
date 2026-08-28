"""Comparative eval: rank-aware retrieval metrics per chunking strategy.

Answer similarity says how *close* the best retrieved chunk came to the expected
answer. It says nothing about where in the ranking the useful chunks landed, so
two strategies that both surface the answer — one at position 1, one at position
5 — score identically. This eval adds the metrics that do look at rank (recall@k,
MRR, nDCG@k) and reports them next to the existing ones, over the same labelled
Q&A set ``/evaluate`` takes.

It runs the **shipped** :class:`services.evaluation.Evaluation` service rather
than a parallel reimplementation, so the numbers here are the ones ``/evaluate``
reports. Only the storage is swapped: :class:`_InMemoryChunks` ranks a strategy's
chunks by cosine similarity, which is what the ``<=>`` operator does in the real
pgvector search, so the eval needs no Postgres. Nothing above that seam — the
relevance rule, the metrics, the aggregation — is duplicated here.

Two datasets, the same pair the chunking comparison uses: ``sample.txt`` is flat
prose and ``structured_sample.txt`` marks up its own sections. Each is scored at
two values of ``k``, because recall@k is defined *at* a cut-off and moves as that
cut-off changes — reporting a single k would hide that.

The labelled questions live in ``evals/data/sample_qa.json`` and are synthetic,
written against documents authored for this repository.

Embedding runs through Ollama, so this eval needs a running Ollama server (the
compose stack provides one). Point it elsewhere with ``OLLAMA_BASE_URL`` /
``OLLAMA_EMBED_MODEL``.

Run it with:
    OLLAMA_BASE_URL=http://localhost:11434 uv run python -m evals.retrieval_ranking_eval

Results are written to ``evals/results/retrieval_ranking.json`` and are a
regenerable artifact, not a one-off screenshot.
"""

import json
from pathlib import Path
from typing import Any, cast

import numpy as np

from dtos.requests import EvaluateRequest, FixedSizeChunkingRequest
from dtos.responses import RetrievedChunk
from evals.fixed_size_chunking_eval import _load_pages
from services.chunking import FixedSizeChunker, SemanticChunker, StructuralChunker
from services.embedding import Embedder, OllamaEmbedder
from services.evaluation import ANSWER_MATCH_THRESHOLD, Evaluation
from services.storage import PostgresStorage

_DATA_DIR = Path(__file__).parent / "data"
_QA_PATH = _DATA_DIR / "sample_qa.json"
_RESULTS_PATH = Path(__file__).parent / "results" / "retrieval_ranking.json"

# Flat prose first, then a document that marks up its own structure.
_DATASETS = ["sample.txt", "structured_sample.txt"]

# Fixed-size baselines to compare the boundary-picking strategies against.
_FIXED_CHUNK_SIZES = [64, 128, 256]

# Cut-offs to report at. recall@k is defined at a cut-off, so a single k would
# hide how much of the ranking a caller actually has to read.
_TOP_K_VALUES = [3, 5]

# The eval scores one synthetic document at a time; the id and role only have to
# satisfy the request model, since the in-memory store holds a single document.
_DOCUMENT_ID = 1
_ACCESS_ROLE = "analyst"


class _InMemoryChunks:
    """Stand-in for pgvector storage so the eval runs without Postgres.

    Ranks a strategy's chunks by cosine similarity to the query embedding, which
    is what the ``<=>`` operator does in the real search. Deletion is a no-op: the
    eval scores every strategy and reports them all, where ``/evaluate`` would
    keep the winner and prune the rest.
    """

    def __init__(
        self, chunks_by_strategy: dict[str, list[str]], embedder: Embedder
    ) -> None:
        self._texts = chunks_by_strategy
        self._vectors = {
            strategy: np.asarray(embedder.embed(texts), dtype=float)
            for strategy, texts in chunks_by_strategy.items()
        }

    def read_chunk_texts_by_strategy(
        self, document_id: int, access_role: str
    ) -> dict[str, list[str]]:
        return self._texts

    def search_chunks(
        self,
        query_embedding: list[float],
        access_role: str,
        top_k: int,
        chunking_strategy: str | None = None,
        document_id: int | None = None,
    ) -> list[RetrievedChunk]:
        """The ``top_k`` chunks of one strategy, most cosine-similar first."""
        texts = self._texts[str(chunking_strategy)]
        vectors = self._vectors[str(chunking_strategy)]
        query = np.asarray(query_embedding, dtype=float)
        denom = np.linalg.norm(vectors, axis=1) * float(np.linalg.norm(query))
        with np.errstate(divide="ignore", invalid="ignore"):
            sims = np.where(denom > 0, (vectors @ query) / denom, 0.0)
        # Descending similarity, ties broken by chunk order for a stable ranking.
        order = np.argsort(-sims, kind="stable")[:top_k]
        return [
            RetrievedChunk(
                document_id=_DOCUMENT_ID,
                document_name="eval",
                chunking_strategy=str(chunking_strategy),
                chunk_index=int(index),
                page_number=1,
                text=texts[int(index)],
                score=float(sims[int(index)]),
            )
            for index in order
        ]

    def delete_chunks_except(self, document_id: int, keep_strategy: str) -> int:
        return 0


def _chunk_every_strategy(pages: list[str], embedder: Embedder) -> dict[str, list[str]]:
    """Chunk one document with every strategy, keyed by strategy name.

    The fixed-size windows are named per size so each is scored as its own
    strategy, the way ``/process`` stores them side by side.
    """
    by_strategy = {
        f"fixed-{size}": FixedSizeChunker(
            FixedSizeChunkingRequest(chunk_size=size)
        ).chunk(pages)
        for size in _FIXED_CHUNK_SIZES
    }
    by_strategy["semantic"] = SemanticChunker(embedder).chunk(pages)
    by_strategy["structural"] = StructuralChunker().chunk(pages)
    return by_strategy


def _run_dataset(name: str, qa_pairs: list[dict[str, str]], embedder: Embedder) -> Any:
    """Score every strategy over one document, at each cut-off."""
    pages = _load_pages(_DATA_DIR / name)
    chunks_by_strategy = _chunk_every_strategy(pages, embedder)
    storage = _InMemoryChunks(chunks_by_strategy, embedder)
    service = Evaluation(embedder=embedder)

    runs = []
    for top_k in _TOP_K_VALUES:
        request = EvaluateRequest(
            document_id=_DOCUMENT_ID,
            access_role=_ACCESS_ROLE,
            qa_pairs=qa_pairs,  # type: ignore[arg-type]  # validated by the model
            top_k=top_k,
        )
        # The service is typed against PostgresStorage; the in-memory store
        # implements the three methods it actually calls.
        response = service.evaluate(request, cast(PostgresStorage, storage))
        runs.append(
            {
                "top_k": top_k,
                "strategies": [item.model_dump() for item in response.evaluations],
            }
        )

    return {
        "dataset": name,
        "questions": len(qa_pairs),
        "chunks_per_strategy": {
            strategy: len(chunks) for strategy, chunks in chunks_by_strategy.items()
        },
        "runs": runs,
    }


def _run() -> dict[str, Any]:
    embedder = OllamaEmbedder.from_env()
    qa_by_dataset = json.loads(_QA_PATH.read_text(encoding="utf-8"))
    return {
        "embedding_model": embedder._model,
        "relevance_threshold": ANSWER_MATCH_THRESHOLD,
        "datasets": [
            _run_dataset(name, qa_by_dataset[name], embedder) for name in _DATASETS
        ],
    }


def _cell(value: float | None) -> str:
    """Format a metric, showing an undefined one as a dash rather than 0."""
    return "-" if value is None else f"{value:.3f}"


def _print_table(payload: dict[str, Any]) -> None:
    header = (
        f"{'strategy':<12} {'chunks':>6} {'ans_sim':>8} {'hit':>6} "
        f"{'recall':>7} {'mrr':>7} {'ndcg':>7} {'kept':>5}"
    )
    for dataset in payload["datasets"]:
        for run in dataset["runs"]:
            print(
                f"\nretrieval ranking - {dataset['dataset']} "
                f"(k={run['top_k']}, {dataset['questions']} questions, "
                f"threshold {payload['relevance_threshold']}, "
                f"embeddings: {payload['embedding_model']})"
            )
            print(header)
            print("-" * len(header))
            for item in run["strategies"]:
                chunks = dataset["chunks_per_strategy"][item["strategy"]]
                print(
                    f"{item['strategy']:<12} {chunks:>6} "
                    f"{item['answer_similarity']:>8.3f} {item['hit_rate']:>6.2f} "
                    f"{_cell(item['recall_at_k']):>7} {item['mrr']:>7.3f} "
                    f"{_cell(item['ndcg_at_k']):>7} "
                    f"{'*' if item['selected'] else '':>5}"
                )


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
