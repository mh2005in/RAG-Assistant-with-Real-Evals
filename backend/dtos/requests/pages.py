"""Request DTOs for selecting which pages of a document to process.

Page exclusion is strategy-agnostic: it describes the document, not how it is
split, so it is applied once before chunking and applies to every chunking
strategy. Keep it out of the per-strategy request DTOs.
"""

from pydantic import BaseModel, Field, TypeAdapter, model_validator


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


class PageExclusion(BaseModel):
    """Pages to leave out of chunking, whatever strategy is used.

    ``exclude_pages`` accepts a mixed list of single page numbers and
    ``PageRange`` objects, e.g. ``[1, 3, {"start": 10, "end": 15}]``. All page
    numbers are 1-based; ranges are inclusive.
    """

    exclude_pages: list[int | PageRange] = Field(
        default_factory=list,
        description="Pages to skip: single page numbers and/or inclusive page ranges.",
    )

    @model_validator(mode="after")
    def _check_single_pages(self) -> "PageExclusion":
        for item in self.exclude_pages:
            if isinstance(item, int) and item < 1:
                raise ValueError(f"page numbers must be >= 1, got {item}")
        return self

    @classmethod
    def from_json_array(cls, raw: str) -> "PageExclusion":
        """Build from a bare JSON array, e.g. ``[1, {"start": 10, "end": 12}]``.

        Callers (the ``exclude_pages`` form field) send just the array — the field
        is already named for it, so there is no redundant wrapper object. Raises
        :class:`pydantic.ValidationError` for malformed JSON or bad page numbers.
        """
        return cls(exclude_pages=_PAGE_ITEMS.validate_json(raw))

    def excluded_page_numbers(self) -> set[int]:
        """Flatten single pages and ranges into one set of page numbers."""
        pages: set[int] = set()
        for item in self.exclude_pages:
            if isinstance(item, PageRange):
                pages |= item.pages()
            else:
                pages.add(item)
        return pages


# Parses/validates the bare JSON array accepted by ``PageExclusion.from_json_array``.
_PAGE_ITEMS: TypeAdapter[list[int | PageRange]] = TypeAdapter(list[int | PageRange])
