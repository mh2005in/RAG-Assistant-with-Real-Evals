"""Tests for document-type detection."""

from dtos.responses import DocType
from services.doc_type import detect_doc_type


def test_detects_pdf_from_magic_bytes() -> None:
    assert detect_doc_type(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n") is DocType.pdf


def test_magic_bytes_win_over_wrong_extension() -> None:
    # Content is a real PDF even though the name claims otherwise.
    assert detect_doc_type(b"%PDF-1.4 ...", filename="notes.txt") is DocType.pdf


def test_falls_back_to_content_type() -> None:
    assert (
        detect_doc_type(b"not-really-a-pdf", content_type="application/pdf")
        is DocType.pdf
    )


def test_falls_back_to_filename_extension() -> None:
    assert detect_doc_type(b"plain bytes", filename="report.PDF") is DocType.pdf


def test_unknown_when_no_signal() -> None:
    assert detect_doc_type(b"hello world", filename="notes.txt") is DocType.unknown


def test_empty_content_is_unknown() -> None:
    assert detect_doc_type(b"") is DocType.unknown
