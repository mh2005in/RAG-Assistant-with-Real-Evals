"""Tests for PDF text extraction."""

from collections.abc import Callable

import pytest

from services.pdf_extraction import extract_pdf_pages


def test_extracts_one_entry_per_page(make_pdf: Callable[[list[str]], bytes]) -> None:
    pdf = make_pdf(["Hello page one", "Second page here"])
    pages = extract_pdf_pages(pdf)

    assert len(pages) == 2
    assert "Hello page one" in pages[0]
    assert "Second page here" in pages[1]


def test_rejects_non_pdf_bytes() -> None:
    with pytest.raises(ValueError, match="not a readable PDF"):
        extract_pdf_pages(b"this is plainly not a pdf")
