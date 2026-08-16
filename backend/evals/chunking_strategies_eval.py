"""Comparative eval: fixed-size vs semantic vs structural chunking.

Runs every implemented chunking strategy over the *same* sample documents and
scores them on the same axes, so a new strategy is measured against the existing
baselines rather than asserted to be better (see CLAUDE.md).

Two datasets, because the strategies differ in what they are able to see:
``sample.txt`` is flat prose with no markup, while ``structured_sample.txt``
carries headings and numbered sections. The structural strategy has nothing to
detect in the first (it falls back to paragraphs) and real markers in the second,
and that gap is exactly what the comparison is for.

Alongside the size distribution, each run is scored with the label-free
cohesion/separation metric from :mod:`services.chunking.coherence` — chunk counts
alone say how a document was cut up, not whether the cuts landed in sensible
places.

Both the semantic strategy and the quality score embed sentences, so this eval
needs a running Ollama server (the compose stack provides one). Point it at a
different host/model with ``OLLAMA_BASE_URL`` / ``OLLAMA_EMBED_MODEL``.

Run it with:
    OLLAMA_BASE_URL=http://localhost:11434 uv run python -m evals.chunking_strategies_eval

Results are written to ``evals/results/chunking_strategies.json`` and are a
regenerable artifact, not a one-off screenshot.
"""

import json
from pathlib import Path
from typing import Any

from dtos.requests import FixedSizeChunkingRequest
from evals.fixed_size_chunking_eval import _load_pages, chunk_metrics
from services.chunking import (
    FixedSizeChunker,
    SemanticChunker,
    StructuralChunker,
    score_chunks,
)
from services.embedding import Embedder, OllamaEmbedder

_DATA_DIR = Path(__file__).parent / "data"
_RESULTS_PATH = Path(__file__).parent / "results" / "chunking_strategies.json"

# Flat prose first, then a document that marks up its own structure.
_DATASETS = [_DATA_DIR / "sample.txt", _DATA_DIR / "structured_sample.txt"]

# Fixed-size baselines to compare the other strategies against.
_FIXED_CHUNK_SIZES = [64, 128, 256]


def _score(chunks: list[str], embedder: Embedder) -> dict[str, Any]:
    """Size metrics plus the label-free quality score for one set of chunks."""
    cohesion, separation, score = score_chunks(chunks, embedder)
    return {
        "cohesion": round(cohesion, 4),
        "separation": round(separation, 4),
        "score": round(score, 4),
    }


def _run_dataset(path: Path, embedder: Embedder) -> dict[str, Any]:
    """Chunk one document with every strategy and score them identically."""
    pages = _load_pages(path)
    runs: list[dict[str, Any]] = []

    for size in _FIXED_CHUNK_SIZES:
        chunks = FixedSizeChunker(FixedSizeChunkingRequest(chunk_size=size)).chunk(
            pages
        )
        runs.append(
            {
                "strategy": "fixed",
                **chunk_metrics(chunks, size),
                **_score(chunks, embedder),
            }
        )

    # Semantic and structural pick their own boundaries, so they have no target
    # chunk_size to be measured against.
    semantic_chunks = SemanticChunker(embedder).chunk(pages)
    runs.append(
        {
            "strategy": "semantic",
            **chunk_metrics(semantic_chunks),
            **_score(semantic_chunks, embedder),
        }
    )

    structural_chunks = StructuralChunker().chunk(pages)
    runs.append(
        {
            "strategy": "structural",
            **chunk_metrics(structural_chunks),
            **_score(structural_chunks, embedder),
        }
    )

    return {
        "dataset": path.name,
        "document_words": sum(len(page.split()) for page in pages),
        "runs": runs,
    }


def _run() -> dict[str, Any]:
    embedder = OllamaEmbedder.from_env()
    return {
        "embedding_model": embedder._model,
        "datasets": [_run_dataset(path, embedder) for path in _DATASETS],
    }


def _print_table(payload: dict[str, Any]) -> None:
    header = (
        f"{'strategy':<11} {'size':>5} {'chunks':>7} {'mean':>7} {'stdev':>7} "
        f"{'min':>5} {'max':>5} {'cohes':>7} {'separ':>7} {'score':>7}"
    )
    for dataset in payload["datasets"]:
        print(
            f"\nchunking strategies - {dataset['dataset']} "
            f"({dataset['document_words']} words, "
            f"embeddings: {payload['embedding_model']})"
        )
        print(header)
        print("-" * len(header))
        for run in dataset["runs"]:
            size = run["chunk_size"] if run["chunk_size"] is not None else "-"
            print(
                f"{run['strategy']:<11} {str(size):>5} {run['num_chunks']:>7} "
                f"{run['mean_chunk_words']:>7} {run['stdev_chunk_words']:>7} "
                f"{run['min_chunk_words']:>5} {run['max_chunk_words']:>5} "
                f"{run['cohesion']:>7} {run['separation']:>7} {run['score']:>7}"
            )


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
