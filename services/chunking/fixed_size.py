"""Fixed-size chunking strategy (chunking stage).

Concatenates the non-excluded page text into a single stream and slices it into
fixed-length windows of ``chunk_size`` characters. This is the simplest possible
baseline: it ignores document structure entirely, which is exactly what makes it
a useful reference point for structure-aware strategies to beat in evals.

The chunking unit is characters. ``FixedSizeChunkingRequest`` describes the size
in generic "units"; this baseline interprets them as characters (deterministic
and tokenizer-free). Overlap is not applied — the request carries no overlap
parameter.
"""

from dtos.requests import FixedSizeChunkingRequest

_PAGE_SEPARATOR = "\n"


class FixedSizeChunker:
    """Split per-page text into fixed-length character chunks.

    Pages listed in the request's ``exclude_pages`` are dropped first; the
    remaining pages are joined in order and sliced into ``chunk_size``-character
    chunks with no overlap.
    """

    def __init__(self, request: FixedSizeChunkingRequest) -> None:
        self._chunk_size = request.chunk_size
        self._excluded = request.excluded_page_numbers()

    def chunk(self, pages: list[str]) -> list[str]:
        kept = [
            text
            for page_number, text in enumerate(pages, start=1)
            if page_number not in self._excluded
        ]
        stream = _PAGE_SEPARATOR.join(kept)
        size = self._chunk_size
        return [stream[i : i + size] for i in range(0, len(stream), size)]
