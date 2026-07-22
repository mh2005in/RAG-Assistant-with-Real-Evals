"""Tests for the FileProcessing service."""

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from dtos.requests import FixedSizeChunkingRequest, PageExclusion
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


class TestExcludePages:
    """Page exclusion is strategy-agnostic and runs before chunking."""

    def test_no_exclusion_returns_pages_unchanged(self) -> None:
        pages = ["one", "two"]

        assert service._exclude_pages(pages, None) == pages
        assert service._exclude_pages(pages, PageExclusion()) == pages

    def test_excluded_pages_are_blanked_not_dropped(self) -> None:
        # Blanking keeps page 3 at index 2, so chunks stay attributed correctly.
        exclusion = PageExclusion.model_validate({"exclude_pages": [2]})

        assert service._exclude_pages(["a", "b", "c"], exclusion) == ["a", "", "c"]

    def test_excludes_ranges_and_single_pages(self) -> None:
        exclusion = PageExclusion.model_validate(
            {"exclude_pages": [1, {"start": 3, "end": 4}]}
        )

        assert service._exclude_pages(["a", "b", "c", "d"], exclusion) == [
            "",
            "b",
            "",
            "",
        ]


class TestProcess:
    """The caller picks no strategy: every one runs, is scored, and one wins."""

    def test_runs_every_strategy_and_selects_one(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        response = service.process(
            make_pdf(["Cats purr. Cats nap.", "Trains run on rails. Trains are fast."]),
            "report.pdf",
            "analyst",
        )

        assert response.processed is True
        assert response.doc_type is DocType.pdf

        # Both implemented strategies were evaluated, exactly one selected.
        assert {item.strategy for item in response.evaluations} == {
            "fixed",
            "semantic",
        }
        selected = [item for item in response.evaluations if item.selected]
        assert len(selected) == 1
        assert response.chunking_strategy == selected[0].strategy

        # Evaluations are ordered best first, and the winner has the top score.
        scores = [item.score for item in response.evaluations]
        assert scores == sorted(scores, reverse=True)
        assert selected[0] is response.evaluations[0]

        # The returned chunks are the winner's.
        assert response.chunk_count == len(response.chunks)
        assert response.chunk_count == selected[0].chunk_count
        assert all(chunk.embedding for chunk in response.chunks)

    def test_stores_every_strategy_then_deletes_the_losers(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = MagicMock()
        storage.insert_document.return_value = StoredDocument(
            document_id=55, chunk_count=9
        )

        response = service.process(
            make_pdf(["Cats purr. Cats nap.", "Trains run on rails. Trains are fast."]),
            "report.pdf",
            "analyst",
            storage=storage,
        )

        assert response.document_id == 55

        # Every candidate is written against a single documents row...
        name, access_role, chunks_by_strategy = storage.insert_document.call_args.args
        assert name == "report.pdf"
        assert access_role == "analyst"
        assert set(chunks_by_strategy) == {"fixed", "semantic"}
        assert all(
            chunk.embedding
            for chunks in chunks_by_strategy.values()
            for chunk in chunks
        )

        # ...then everything but the winner is deleted, so one strategy remains.
        storage.delete_chunks_except.assert_called_once_with(
            55, response.chunking_strategy
        )

    def test_uses_the_given_chunk_size_for_the_fixed_candidate(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = MagicMock()
        storage.insert_document.return_value = StoredDocument(
            document_id=1, chunk_count=1
        )

        service.process(
            make_pdf(["one two three four five six seven eight nine ten."]),
            "report.pdf",
            "analyst",
            FixedSizeChunkingRequest(chunk_size=3),
            storage=storage,
        )

        _, _, chunks_by_strategy = storage.insert_document.call_args.args
        assert all(
            len(chunk.text.split()) <= 3 for chunk in chunks_by_strategy["fixed"]
        )

    def test_non_pdf_is_not_chunked_or_persisted(self) -> None:
        storage = MagicMock()

        response = service.process(
            b"just some plain text",
            "notes.txt",
            "analyst",
            filename="notes.txt",
            storage=storage,
        )

        assert response.doc_type is DocType.unknown
        assert response.chunks == []
        assert response.chunk_count == 0
        assert response.document_id is None
        assert response.chunking_strategy is None
        assert response.evaluations == []
        storage.insert_document.assert_not_called()
        storage.delete_chunks_except.assert_not_called()

    def test_excluded_pages_are_left_out_of_chunks(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        response = service.process(
            make_pdf(["KEEPME one.", "DROPME two.", "KEEPTOO three."]),
            "report.pdf",
            "analyst",
            page_exclusion=PageExclusion.model_validate({"exclude_pages": [2]}),
        )

        joined = " ".join(chunk.text for chunk in response.chunks)
        assert "KEEPME" in joined
        assert "KEEPTOO" in joined
        assert "DROPME" not in joined

    def test_exclusion_preserves_page_numbers_of_later_pages(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        response = service.process(
            make_pdf(["DROPME one.", "KEEPME two."]),
            "report.pdf",
            "analyst",
            page_exclusion=PageExclusion.model_validate({"exclude_pages": [1]}),
        )

        # Page 1 was excluded, so every surviving chunk must report page 2.
        assert {chunk.page_number for chunk in response.chunks} == {2}
