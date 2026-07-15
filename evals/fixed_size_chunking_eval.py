"""Reproducible eval for the fixed-size chunking strategy (chunking stage).

Fixed-size is the first chunking strategy, so this eval establishes a baseline:
it runs the strategy over a fixed sample document across several window sizes and
records concrete metrics (chunk counts, size distribution, how full chunks are).
Later structure-aware strategies plug into the same ``chunk_metrics`` helper so
comparisons are apples-to-apples (see CLAUDE.md).

Run it with:
    uv run python -m evals.fixed_size_chunking_eval

Results are written to ``evals/results/fixed_size_chunking.json`` and are a
regenerable artifact, not a one-off screenshot.
"""

import json
import statistics
from pathlib import Path
from typing import Any

from dtos.requests import FixedSizeChunkingRequest
from services.chunking import FixedSizeChunker

_DATA_PATH = Path(__file__).parent / "data" / "sample.txt"
_RESULTS_PATH = Path(__file__).parent / "results" / "fixed_size_chunking.json"

# Window sizes (characters) compared in this baseline sweep.
_CHUNK_SIZES = [256, 512, 1024]


def load_pages(path: Path = _DATA_PATH) -> list[str]:
    """Load the sample document as per-page text (form feed splits pages)."""
    text = path.read_text(encoding="utf-8")
    return text.split("\f")


def chunk_metrics(chunks: list[str], chunk_size: int) -> dict[str, Any]:
    """Summary metrics for a set of chunks produced at ``chunk_size``.

    Strategy-agnostic: any chunker's output can be scored with this so future
    strategies are measured on the same axes.
    """
    lengths = [len(chunk) for chunk in chunks]
    total_chars = sum(lengths)
    return {
        "chunk_size": chunk_size,
        "num_chunks": len(chunks),
        "total_chars": total_chars,
        "min_chunk_chars": min(lengths, default=0),
        "max_chunk_chars": max(lengths, default=0),
        "mean_chunk_chars": round(statistics.fmean(lengths), 2) if lengths else 0.0,
        "stdev_chunk_chars": (
            round(statistics.stdev(lengths), 2) if len(lengths) > 1 else 0.0
        ),
        # Average fraction of a window that is actually filled. Fixed-size fills
        # every chunk but the last, so this trends toward 1.0 as the doc grows.
        "fill_ratio": (
            round(total_chars / (len(chunks) * chunk_size), 4) if chunks else 0.0
        ),
        # Chunks shorter than the target window (only the tail, for fixed-size).
        "undersized_chunks": sum(1 for length in lengths if length < chunk_size),
    }


def run() -> dict[str, Any]:
    """Run the fixed-size sweep and return the results payload."""
    pages = load_pages()
    results = []
    for size in _CHUNK_SIZES:
        request = FixedSizeChunkingRequest(chunk_size=size)
        chunks = FixedSizeChunker(request).chunk(pages)
        results.append(chunk_metrics(chunks, size))
    return {
        "strategy": "fixed",
        "dataset": _DATA_PATH.name,
        "document_chars": sum(len(page) for page in pages),
        "runs": results,
    }


def _print_table(payload: dict[str, Any]) -> None:
    header = f"{'size':>6} {'chunks':>7} {'mean':>8} {'stdev':>8} {'fill':>7}"
    print(
        f"fixed-size chunking - {payload['dataset']} "
        f"({payload['document_chars']} chars)"
    )
    print(header)
    print("-" * len(header))
    for run_result in payload["runs"]:
        print(
            f"{run_result['chunk_size']:>6} "
            f"{run_result['num_chunks']:>7} "
            f"{run_result['mean_chunk_chars']:>8} "
            f"{run_result['stdev_chunk_chars']:>8} "
            f"{run_result['fill_ratio']:>7}"
        )


def main() -> None:
    payload = run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
