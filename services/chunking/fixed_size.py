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

from bisect import bisect_right

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
        return [text for _, text in self.chunk_with_pages(pages)]

    def chunk_with_pages(self, pages: list[str]) -> list[tuple[int, str]]:
        """Slice pages into fixed windows, tagging each chunk with its start page.

        Produces the same windows as :meth:`chunk`, but pairs each chunk with the
        1-based source page it *begins* on. A fixed-size window can span a page
        boundary; the reported page is the one containing the chunk's first
        character.
        """
        kept = [
            (page_number, text)
            for page_number, text in enumerate(pages, start=1)
            if page_number not in self._excluded
        ]
        stream = _PAGE_SEPARATOR.join(text for _, text in kept)

        # Offset in the joined stream where each kept page begins, so a chunk's
        # start offset can be mapped back to its source page.
        page_starts: list[int] = []
        page_numbers: list[int] = []
        offset = 0
        for page_number, text in kept:
            page_starts.append(offset)
            page_numbers.append(page_number)
            offset += len(text) + len(_PAGE_SEPARATOR)

        size = self._chunk_size
        result: list[tuple[int, str]] = []
        for start in range(0, len(stream), size):
            # The chunk starts inside the page with the greatest start <= offset.
            page_index = bisect_right(page_starts, start) - 1
            result.append((page_numbers[page_index], stream[start : start + size]))
        return result
