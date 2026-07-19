"""Tests for the FileProcessing service."""

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from dtos.requests import ChunkingStrategy, FixedSizeChunkingRequest
from dtos.responses import DocType, StoredDocument
from services.file_processing import FileProcessing

service = FileProcessing()


class TestDetectDocType:
    def test_detects_pdf_from_magic_bytes(self) -> None:
        assert service._detect_doc_type(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n") is DocType.pdf

    def test_magic_bytes_win_over_wrong_extension(self) -> None:
        # Content is a real PDF even though the name claims otherwise.
        assert (
            service._detect_doc_type(b"%PDF-1.4 ...", filename="notes.txt")
            is DocType.pdf
        )

    def test_falls_back_to_content_type(self) -> None:
        assert (
            service._detect_doc_type(
                b"not-really-a-pdf", content_type="application/pdf"
            )
            is DocType.pdf
        )

    def test_falls_back_to_filename_extension(self) -> None:
        assert service._detect_doc_type(b"plain bytes", filename="report.PDF") is (
            DocType.pdf
        )

    def test_unknown_when_no_signal(self) -> None:
        assert (
            service._detect_doc_type(b"hello world", filename="notes.txt")
            is DocType.unknown
        )

    def test_empty_content_is_unknown(self) -> None:
        assert service._detect_doc_type(b"") is DocType.unknown


class TestExtractPdfPages:
    def test_extracts_one_entry_per_page(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        pages = service._extract_pdf_pages(make_pdf(["Hello page one", "Second page"]))

        assert len(pages) == 2
        assert "Hello page one" in pages[0]
        assert "Second page" in pages[1]

    def test_rejects_non_pdf_bytes(self) -> None:
        with pytest.raises(ValueError, match="not a readable PDF"):
            service._extract_pdf_pages(b"this is plainly not a pdf")


class TestProcess:
    def test_chunks_pdf_with_fixed_strategy(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        response = service.process(
            make_pdf(["Page one text.", "Page two text."]),
            ChunkingStrategy.fixed,
            "report.pdf",
            "analyst",
            FixedSizeChunkingRequest(chunk_size=8),
        )

        assert response.processed is True
        assert response.doc_type is DocType.pdf
        assert response.chunk_count == len(response.chunks)
        assert response.chunk_count > 0
        assert all(len(chunk.text.split()) <= 8 for chunk in response.chunks)
        # Every chunk is embedded and tagged with a source page.
        assert all(chunk.embedding for chunk in response.chunks)
        assert all(chunk.page_number >= 1 for chunk in response.chunks)
        # Nothing was persisted without a storage handle.
        assert response.document_id is None

    def test_persists_full_chunks_when_storage_is_given(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = MagicMock()
        storage.insert_document.return_value = StoredDocument(
            document_id=55, chunk_count=1
        )

        response = service.process(
            make_pdf(["Page one text.", "Page two text."]),
            ChunkingStrategy.fixed,
            "report.pdf",
            "analyst",
            FixedSizeChunkingRequest(chunk_size=100),
            storage=storage,
        )

        assert response.document_id == 55
        name, access_role, chunks = storage.insert_document.call_args.args
        assert name == "report.pdf"
        assert access_role == "analyst"
        # The full, embedded chunks are persisted (not the clipped response copies).
        assert chunks and all(chunk.embedding for chunk in chunks)

    def test_non_pdf_is_not_chunked_or_persisted(self) -> None:
        storage = MagicMock()

        response = service.process(
            b"just some plain text",
            ChunkingStrategy.fixed,
            "notes.txt",
            "analyst",
            FixedSizeChunkingRequest(chunk_size=8),
            filename="notes.txt",
            storage=storage,
        )

        assert response.doc_type is DocType.unknown
        assert response.chunks == []
        assert response.chunk_count == 0
        assert response.document_id is None
        storage.insert_document.assert_not_called()

    def test_fixed_strategy_requires_fixed_size(self) -> None:
        with pytest.raises(ValueError, match="fixed_size parameters are required"):
            service.process(b"%PDF-1.4", ChunkingStrategy.fixed, "doc.pdf", "analyst")
