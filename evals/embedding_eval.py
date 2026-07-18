"""Reproducible eval for the embedding stage (sentence-transformers).

Establishes a baseline for embedding chunk text with all-mpnet-base-v2 and, to
exercise the configurable ``model_name``, compares it against a smaller model on
the same texts so the trade-offs are measured apples-to-apples (see CLAUDE.md):
vector dimension, encode throughput, and how well the vectors separate related
from unrelated text.

The texts are produced by slicing the sample document with the existing
fixed-size chunker, so the embedding stage is measured on realistic chunk sizes.

Run it with (downloads the models on first run):
    uv run python -m evals.embedding_eval

Results are written to ``evals/results/embedding.json`` and are a regenerable
artifact, not a one-off screenshot.
"""

import json
import statistics
import time
from itertools import combinations
from pathlib import Path
from typing import Any

from dtos.requests import EmbeddingRequest, FixedSizeChunkingRequest
from dtos.responses import Chunk
from services.chunking import FixedSizeChunker
from services.embedding import SentenceTransformerEmbedder

_DATA_PATH = Path(__file__).parent / "data" / "sample.txt"
_RESULTS_PATH = Path(__file__).parent / "results" / "embedding.json"

# Chunk window (words) used to slice the sample into texts to embed.
_CHUNK_SIZE = 64

# Models compared. all-mpnet-base-v2 is the configured default; the MiniLM model
# is a smaller, faster alternative included to show model_name is configurable.
_MODELS = [
    "sentence-transformers/all-mpnet-base-v2",
    "sentence-transformers/all-MiniLM-L6-v2",
]


def _load_pages(path: Path = _DATA_PATH) -> list[str]:
    """Load the sample document as per-page text (form feed splits pages)."""
    return path.read_text(encoding="utf-8").split("\f")


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors (0.0 if either is degenerate)."""
    norm = (_dot(a, a) ** 0.5) * (_dot(b, b) ** 0.5)
    return _dot(a, b) / norm if norm else 0.0


def embedding_metrics(
    model_name: str, chunks: list[Chunk], seconds: float
) -> dict[str, Any]:
    """Summary metrics for one model's embeddings over ``chunks``.

    Model-agnostic: any embedder's output can be scored with this so future
    embedding models are measured on the same axes.
    """
    vectors = [chunk.embedding for chunk in chunks]
    dims = {len(vector) for vector in vectors}
    similarities = [_cosine(a, b) for a, b in combinations(vectors, 2)]
    return {
        "model_name": model_name,
        "num_texts": len(chunks),
        "embedding_dim": dims.pop() if len(dims) == 1 else sorted(dims),
        "encode_seconds": round(seconds, 4),
        "texts_per_second": round(len(chunks) / seconds, 2) if seconds else 0.0,
        "mean_vector_norm": round(
            statistics.fmean(_dot(v, v) ** 0.5 for v in vectors), 4
        )
        if vectors
        else 0.0,
        # Sanity signal: mean/max pairwise cosine over chunks of one document.
        "mean_pairwise_cosine": (
            round(statistics.fmean(similarities), 4) if similarities else 0.0
        ),
        "max_pairwise_cosine": round(max(similarities), 4) if similarities else 0.0,
    }


def _run() -> dict[str, Any]:
    """Embed the sample chunks with each model and return the results payload."""
    pages = _load_pages()
    texts = FixedSizeChunker(FixedSizeChunkingRequest(chunk_size=_CHUNK_SIZE)).chunk(
        pages
    )
    base_chunks = [Chunk.from_page(1, text) for text in texts]

    runs = []
    for model_name in _MODELS:
        embedder = SentenceTransformerEmbedder(EmbeddingRequest(model_name=model_name))
        start = time.perf_counter()
        embedded = embedder.embed_chunks(base_chunks)
        seconds = time.perf_counter() - start
        runs.append(embedding_metrics(model_name, embedded, seconds))

    return {
        "stage": "embedding",
        "dataset": _DATA_PATH.name,
        "device": EmbeddingRequest().device.value,
        "chunk_size": _CHUNK_SIZE,
        "runs": runs,
    }


def _print_table(payload: dict[str, Any]) -> None:
    header = f"{'model':<44} {'dim':>5} {'texts/s':>8} {'meancos':>8}"
    print(f"embedding - {payload['dataset']} (device={payload['device']})")
    print(header)
    print("-" * len(header))
    for run_result in payload["runs"]:
        print(
            f"{run_result['model_name']:<44} "
            f"{run_result['embedding_dim']!s:>5} "
            f"{run_result['texts_per_second']:>8} "
            f"{run_result['mean_pairwise_cosine']:>8}"
        )


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
