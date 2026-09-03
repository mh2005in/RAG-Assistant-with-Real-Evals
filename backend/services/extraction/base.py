"""Common interface for extractors (extraction stage).

Every extractor consumes a document's raw bytes and returns its text as a list of
per-page strings, page 1 at index 0 — the shape the chunking stage consumes and
the shape page exclusion (``REQ-EXT-02``) operates on. Keeping the interface
uniform is what lets an eval compare one source format against another
apples-to-apples (see CLAUDE.md), and is the seam OCR (``REQ-EXT-03``) and web
scraping (``REQ-EXT-05``) plug into.

**Pagination is a property of the format, not of the pipeline.** A PDF carries
real page boundaries; DOCX, HTML and plain text do not — their pagination is
decided at render time by a viewer, not stored in the file. Rather than invent
page breaks that the source never had, a paginationless format extracts to a
*single* page (see :func:`single_page`). Everything downstream keeps working:
chunks are attributed to page 1, per-page stats become whole-document stats, and
excluding page 1 excludes the document.
"""

import re
from typing import Protocol

# Runs of blank lines separate blocks; the chunking stage reads a blank line as a
# paragraph break (the structural strategy falls back to paragraphs), so blocks
# are rejoined with exactly one.
_BLOCK_SEPARATOR = "\n\n"
_LINE_WHITESPACE = re.compile(r"[^\S\n]+")


class Extractor(Protocol):
    """An extraction strategy: a document's bytes in, per-page text out."""

    def extract(self, content: bytes) -> list[str]:
        """Extract ``content`` into per-page text, page 1 at index 0.

        Raises :class:`ValueError` if ``content`` is not readable as the format
        the extractor handles.
        """
        ...


def single_page(blocks: list[str]) -> list[str]:
    """Join ``blocks`` into the one page a paginationless format extracts to.

    Blank blocks are dropped and each block's internal whitespace is collapsed,
    so the text a DOCX or HTML document yields is separated the same way a PDF's
    is — by a blank line — rather than by whatever run of spaces, tabs and empty
    paragraphs the source happened to use for layout.
    """
    cleaned = [
        stripped
        for block in blocks
        if (stripped := _LINE_WHITESPACE.sub(" ", block).strip())
    ]
    return [_BLOCK_SEPARATOR.join(cleaned)]
