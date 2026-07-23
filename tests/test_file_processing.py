"""Tests for the FileProcessing service."""

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from dtos.requests import FixedSizeChunkingRequest, PageExclusion
from dtos.responses import Chunk, DocType
from services.file_processing import FileProcessing

service = FileProcessing()


def _fake_storage(document_id: int = 55) -> MagicMock:
    """A storage mock whose ``create_document`` returns ``document_id``."""
    storage = MagicMock()
    storage.create_document.return_value = document_id
    return storage


def _stored_chunks(storage: MagicMock, strategy: str = "fixed") -> list[Chunk]:
    """The chunks a mocked storage was streamed for one strategy, in order.

    The service persists one chunk at a time via ``insert_chunk(document_id,
    strategy, index, chunk)``, so gather the ``chunk`` arg of each call tagged
    with ``strategy``.
    """
    return [
        call.args[3]
        for call in storage.insert_chunk.call_args_list
        if call.args[1] == strategy
    ]


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
    """The caller picks no strategy: every one runs and all are stored, unscored."""

    def test_runs_every_strategy_and_reports_them(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        response = service.process(
            make_pdf(["Cats purr. Cats nap.", "Trains run on rails. Trains are fast."]),
            "report.pdf",
            "analyst",
        )

        assert response.processed is True
        assert response.doc_type is DocType.pdf

        # Both implemented strategies were chunked and reported, each with a
        # positive chunk count. No winner is chosen here (that is /evaluate's job).
        assert {item.strategy for item in response.strategies} == {"fixed", "semantic"}
        assert all(item.chunk_count > 0 for item in response.strategies)

    def test_streams_every_strategy_without_scoring_or_pruning(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = _fake_storage(document_id=55)

        response = service.process(
            make_pdf(["Cats purr. Cats nap.", "Trains run on rails. Trains are fast."]),
            "report.pdf",
            "analyst",
            storage=storage,
        )

        assert response.document_id == 55

        # The document row is created once, under the given name and role...
        storage.create_document.assert_called_once_with("report.pdf", "analyst")
        # ...then each chunk is streamed with insert_chunk, one call per chunk,
        # every chunk carrying its embedding.
        streamed = storage.insert_chunk.call_args_list
        assert {call.args[1] for call in streamed} == {"fixed", "semantic"}
        assert all(call.args[0] == 55 for call in streamed)
        assert all(call.args[3].embedding for call in streamed)

        # Nothing is scored or deleted here: pruning is deferred to /evaluate.
        storage.delete_chunks_except.assert_not_called()
        # The response counts match how many chunks were streamed per strategy.
        streamed_counts = {"fixed": 0, "semantic": 0}
        for call in streamed:
            streamed_counts[call.args[1]] += 1
        assert {
            item.strategy: item.chunk_count for item in response.strategies
        } == streamed_counts

    def test_streams_chunks_numbered_from_zero_per_strategy(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = _fake_storage()

        service.process(
            make_pdf(
                ["Cats purr. Cats nap. Cats groom.", "Trains run. Trains are fast."]
            ),
            "report.pdf",
            "analyst",
            FixedSizeChunkingRequest(chunk_size=3),
            storage=storage,
        )

        # Each strategy's chunk_index restarts at 0 and increments by one.
        for strategy in ("fixed", "semantic"):
            indices = [
                call.args[2]
                for call in storage.insert_chunk.call_args_list
                if call.args[1] == strategy
            ]
            assert indices == list(range(len(indices)))
            assert indices[0] == 0

    def test_uses_the_given_chunk_size_for_the_fixed_candidate(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = _fake_storage(document_id=1)

        service.process(
            make_pdf(["one two three four five six seven eight nine ten."]),
            "report.pdf",
            "analyst",
            FixedSizeChunkingRequest(chunk_size=3),
            storage=storage,
        )

        assert all(
            len(chunk.text.split()) <= 3 for chunk in _stored_chunks(storage, "fixed")
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
        assert response.document_id is None
        assert response.strategies == []
        storage.create_document.assert_not_called()
        storage.insert_chunk.assert_not_called()
        storage.delete_chunks_except.assert_not_called()

    def test_excluded_pages_are_left_out_of_chunks(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = _fake_storage(document_id=1)

        service.process(
            make_pdf(["KEEPME one.", "DROPME two.", "KEEPTOO three."]),
            "report.pdf",
            "analyst",
            page_exclusion=PageExclusion.model_validate({"exclude_pages": [2]}),
            storage=storage,
        )

        # The response no longer echoes chunks, so check what was stored.
        joined = " ".join(chunk.text for chunk in _stored_chunks(storage))
        assert "KEEPME" in joined
        assert "KEEPTOO" in joined
        assert "DROPME" not in joined

    def test_exclusion_preserves_page_numbers_of_later_pages(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = _fake_storage(document_id=1)

        service.process(
            make_pdf(["DROPME one.", "KEEPME two."]),
            "report.pdf",
            "analyst",
            page_exclusion=PageExclusion.model_validate({"exclude_pages": [1]}),
            storage=storage,
        )

        # Page 1 was excluded, so every surviving chunk must report page 2.
        assert {chunk.page_number for chunk in _stored_chunks(storage)} == {2}
