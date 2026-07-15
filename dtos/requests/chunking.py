"""Request DTOs for chunking strategies."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ChunkingStrategy(str, Enum):
    """Chunking strategies under evaluation (see README)."""

    fixed = "fixed"
    semantic = "semantic"
    structural = "structural"
    recursive = "recursive"
    llm = "llm"


class PageRange(BaseModel):
    """An inclusive range of 1-based page numbers."""

    start: int = Field(
        ..., ge=1, description="First page in the range (1-based, inclusive)."
    )
    end: int = Field(
        ..., ge=1, description="Last page in the range (1-based, inclusive)."
    )

    @model_validator(mode="after")
    def _check_order(self) -> "PageRange":
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self

    def pages(self) -> set[int]:
        """Expand the range into the set of page numbers it covers."""
        return set(range(self.start, self.end + 1))


class FixedSizeChunkingRequest(BaseModel):
    """Parameters for the fixed-size chunking strategy.

    ``exclude_pages`` accepts a mixed list of single page numbers and
    ``PageRange`` objects, e.g. ``[1, 3, {"start": 10, "end": 15}]``.
    All page numbers are 1-based; ranges are inclusive.
    """

    chunk_size: int = Field(
        ...,
        gt=0,
        description="Number of units (e.g. characters/tokens) per chunk.",
    )
    exclude_pages: list[int | PageRange] = Field(
        default_factory=list,
        description="Pages to skip: single page numbers and/or inclusive page ranges.",
    )

    @model_validator(mode="after")
    def _check_single_pages(self) -> "FixedSizeChunkingRequest":
        for item in self.exclude_pages:
            if isinstance(item, int) and item < 1:
                raise ValueError(f"page numbers must be >= 1, got {item}")
        return self

    def excluded_page_numbers(self) -> set[int]:
        """Flatten single pages and ranges into one set of page numbers."""
        pages: set[int] = set()
        for item in self.exclude_pages:
            if isinstance(item, PageRange):
                pages |= item.pages()
            else:
                pages.add(item)
        return pages
