"""Shared pytest fixtures.

Provides a small in-memory PDF builder so tests can exercise real PDF
extraction without any files on disk or network access.
"""

from collections.abc import Callable

import pymupdf
import pytest


@pytest.fixture
def make_pdf() -> Callable[[list[str]], bytes]:
    """Return a factory that builds a PDF (as bytes) from per-page text."""

    def _build(pages: list[str]) -> bytes:
        doc = pymupdf.open()
        try:
            for text in pages:
                page = doc.new_page()
                page.insert_text((72, 72), text)
            return doc.tobytes()
        finally:
            doc.close()

    return _build
