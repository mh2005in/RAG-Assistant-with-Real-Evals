"""PDF text extraction (extraction stage).

Extracts per-page text from a PDF using PyMuPDF (see README). Returning one
string per page lets downstream chunking honour page-level options such as
excluded pages.
"""

import pymupdf


def extract_pdf_pages(content: bytes) -> list[str]:
    """Extract text from a PDF, one entry per page (page 1 at index 0).

    Raises :class:`ValueError` if ``content`` is not a readable PDF.
    """
    try:
        with pymupdf.open(stream=content, filetype="pdf") as doc:
            return [page.get_text() for page in doc]
    except Exception as exc:  # PyMuPDF surfaces several error types for bad input
        raise ValueError("content is not a readable PDF") from exc
