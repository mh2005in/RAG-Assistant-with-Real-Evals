"""Common interface for chunking strategies (chunking stage).

Every strategy consumes a document as a list of per-page text (page 1 at
index 0) and returns an ordered list of text chunks. Keeping the interface
uniform lets evals compare strategies apples-to-apples (see CLAUDE.md).

Page exclusion is applied upstream and is common to every strategy, so an
excluded page simply arrives blank and contributes nothing.
"""

from typing import Protocol


class Chunker(Protocol):
    """A chunking strategy: per-page text in, ordered chunks out."""

    def chunk(self, pages: list[str]) -> list[str]:
        """Split ``pages`` into an ordered list of chunks."""
        ...

    def chunk_with_pages(self, pages: list[str]) -> list[tuple[int, str]]:
        """Split ``pages``, pairing each chunk with the page it begins on."""
        ...
