"""Fixed-size chunking strategy (chunking stage).

Splits the non-excluded page text into fixed-length windows of ``chunk_size``
*words*. This is the simplest possible baseline: it ignores document structure
entirely, which is exactly what makes it a useful reference point for
structure-aware strategies to beat in evals.

The chunking unit is whitespace-split words. ``FixedSizeChunkingRequest``
describes the size in generic "units"; this baseline interprets them as words
(deterministic and tokenizer-free). Words are re-joined with single spaces, so
original intra-page whitespace is normalized. Overlap is not applied — the
request carries no overlap parameter.
"""

from dtos.requests import FixedSizeChunkingRequest


class FixedSizeChunker:
    """Split per-page text into fixed-length word chunks.

    Pages listed in the request's ``exclude_pages`` are dropped first; the words
    of the remaining pages are taken in order and grouped into ``chunk_size``-word
    chunks with no overlap.
    """

    def __init__(self, request: FixedSizeChunkingRequest) -> None:
        self._chunk_size = request.chunk_size
        self._excluded = request.excluded_page_numbers()

    def chunk(self, pages: list[str]) -> list[str]:
        return [text for _, text in self.chunk_with_pages(pages)]

    def chunk_with_pages(self, pages: list[str]) -> list[tuple[int, str]]:
        """Group words into fixed windows, tagging each chunk with its start page.

        Produces the same windows as :meth:`chunk`, but pairs each chunk with the
        1-based source page it *begins* on. A fixed-size window can span a page
        boundary; the reported page is the one containing the chunk's first word.
        """
        # Flatten the kept pages into a stream of (word, source page) pairs so a
        # chunk's start word can be mapped back to the page it began on.
        words: list[tuple[str, int]] = []
        for page_number, text in enumerate(pages, start=1):
            if page_number in self._excluded:
                continue
            words.extend((word, page_number) for word in text.split())

        size = self._chunk_size
        result: list[tuple[int, str]] = []
        for start in range(0, len(words), size):
            window = words[start : start + size]
            page_number = window[0][1]
            result.append((page_number, " ".join(word for word, _ in window)))
        return result
