"""Comparative eval: fixed-size vs semantic chunking (chunking stage).

Runs every implemented chunking strategy over the *same* sample document and
scores them on the same axes, so a new strategy is measured against the existing
baseline rather than asserted to be better (see CLAUDE.md).

Semantic chunking embeds each sentence, so this eval needs a running Ollama
server (the compose stack provides one). Point it at a different host/model with
``OLLAMA_BASE_URL`` / ``OLLAMA_EMBED_MODEL``.

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
from services.chunking import FixedSizeChunker, SemanticChunker
from services.embedding import OllamaEmbedder

_DATA_PATH = Path(__file__).parent / "data" / "sample.txt"
_RESULTS_PATH = Path(__file__).parent / "results" / "chunking_strategies.json"

# Fixed-size baselines to compare the semantic strategy against.
_FIXED_CHUNK_SIZES = [64, 128, 256]


def _run() -> dict[str, Any]:
    """Chunk the sample with every strategy and score them identically."""
    pages = _load_pages(_DATA_PATH)
    runs: list[dict[str, Any]] = []

    for size in _FIXED_CHUNK_SIZES:
        chunker = FixedSizeChunker(FixedSizeChunkingRequest(chunk_size=size))
        metrics = chunk_metrics(chunker.chunk(pages), size)
        runs.append({"strategy": "fixed", **metrics})

    # Semantic picks its own boundaries, so it has no target chunk_size.
    embedder = OllamaEmbedder.from_env()
    semantic_chunks = SemanticChunker(embedder).chunk(pages)
    runs.append({"strategy": "semantic", **chunk_metrics(semantic_chunks)})

    return {
        "dataset": _DATA_PATH.name,
        "document_words": sum(len(page.split()) for page in pages),
        "embedding_model": embedder._model,
        "runs": runs,
    }


def _print_table(payload: dict[str, Any]) -> None:
    header = (
        f"{'strategy':<10} {'size':>6} {'chunks':>7} "
        f"{'mean':>8} {'stdev':>8} {'min':>5} {'max':>6}"
    )
    print(
        f"chunking strategies - {payload['dataset']} "
        f"({payload['document_words']} words, embeddings: {payload['embedding_model']})"
    )
    print(header)
    print("-" * len(header))
    for run in payload["runs"]:
        size = run["chunk_size"] if run["chunk_size"] is not None else "-"
        print(
            f"{run['strategy']:<10} {str(size):>6} {run['num_chunks']:>7} "
            f"{run['mean_chunk_words']:>8} {run['stdev_chunk_words']:>8} "
            f"{run['min_chunk_words']:>5} {run['max_chunk_words']:>6}"
        )


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
