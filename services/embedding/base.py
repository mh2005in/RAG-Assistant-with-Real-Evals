"""Common interface for embedding strategies (embedding stage).

Every embedder turns an ordered list of texts into an ordered list of vectors
(one per text, same order), and can fill the ``embedding`` of a list of chunks.
Keeping the interface uniform lets evals compare embedding models
apples-to-apples (see CLAUDE.md).
"""

from typing import Protocol

from dtos.responses import Chunk


class Embedder(Protocol):
    """An embedding strategy: texts in, one vector per text out."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` into vectors, preserving order."""
        ...

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Return copies of ``chunks`` with their ``embedding`` filled in."""
        ...
