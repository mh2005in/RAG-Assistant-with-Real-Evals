"""Common interface for chunking strategies (chunking stage).

Every strategy consumes a document as a list of per-page text (page 1 at
index 0) and returns an ordered list of text chunks. Keeping the interface
uniform lets evals compare strategies apples-to-apples (see CLAUDE.md).
"""

from typing import Protocol


class Chunker(Protocol):
    """A chunking strategy: per-page text in, ordered chunks out."""

    def chunk(self, pages: list[str]) -> list[str]:
        """Split ``pages`` into an ordered list of chunks."""
        ...
