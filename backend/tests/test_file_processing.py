"""Tests for the FileProcessing service."""

import zipfile
from collections.abc import Callable
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from dtos.requests import (
    FixedSizeChunkingRequest,
    PageExclusion,
    StructuralChunkingRequest,
)
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

    def test_detects_docx_from_its_package_entry(
        self, make_docx: Callable[[list[str]], bytes]
    ) -> None:
        assert service._detect_doc_type(make_docx(["Some prose."])) is DocType.docx

    def test_a_zip_without_a_word_body_is_not_docx(self) -> None:
        # .xlsx and .pptx share the container; only the body part tells them apart.
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            package.writestr("xl/workbook.xml", "<workbook/>")

        assert service._detect_doc_type(buffer.getvalue()) is DocType.unknown

    def test_detects_html_from_its_markup(self) -> None:
        assert (
            service._detect_doc_type(b"<!DOCTYPE html><html><body>hi</body></html>")
            is DocType.html
        )

    def test_plain_text_is_identified_by_extension(self) -> None:
        # Plain text has no signature of its own, so it is the one format that
        # depends on what the caller declares.
        assert service._detect_doc_type(b"hello world", filename="notes.txt") is (
            DocType.text
        )

    def test_plain_text_is_identified_by_content_type(self) -> None:
        assert (
            service._detect_doc_type(b"hello world", content_type="text/plain")
            is DocType.text
        )

    def test_unknown_when_no_signal(self) -> None:
        # Bytes that decode are not thereby prose: without a declared type or a
        # known extension there is nothing to say this is a document.
        assert service._detect_doc_type(b"hello world") is DocType.unknown

    def test_empty_content_is_unknown(self) -> None:
        assert service._detect_doc_type(b"") is DocType.unknown


class TestExtractPages:
    """The seam onto :mod:`services.extraction`; the extractors are tested there."""

    def test_extracts_one_entry_per_page_for_a_pdf(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        pages = service._extract_pages(
            make_pdf(["Hello page one", "Second page"]), DocType.pdf
        )

        assert len(pages) == 2
        assert "Hello page one" in pages[0]
        assert "Second page" in pages[1]

    @pytest.mark.parametrize(
        ("doc_type", "content"),
        [
            (DocType.html, b"<html><body><p>One</p><p>Two</p></body></html>"),
            (DocType.text, b"One\n\nTwo"),
        ],
    )
    def test_paginationless_formats_extract_to_exactly_one_page(
        self, doc_type: DocType, content: bytes
    ) -> None:
        # Their pagination is a render-time choice, so there is no page break to
        # report; per-page stats become whole-document stats.
        assert service._extract_pages(content, doc_type) == ["One\n\nTwo"]

    def test_docx_extracts_to_exactly_one_page(
        self, make_docx: Callable[[list[str]], bytes]
    ) -> None:
        assert service._extract_pages(make_docx(["One", "Two"]), DocType.docx) == [
            "One\n\nTwo"
        ]

    def test_rejects_bytes_that_are_not_the_detected_type(self) -> None:
        with pytest.raises(ValueError, match="not a readable PDF"):
            service._extract_pages(b"this is plainly not a pdf", DocType.pdf)

    def test_rejects_a_type_nothing_can_read(self) -> None:
        with pytest.raises(ValueError, match="no extractor"):
            service._extract_pages(b"anything", DocType.unknown)


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

        # Every implemented strategy was chunked and reported, each with a
        # positive chunk count. No winner is chosen here (that is /evaluate's job).
        assert {item.strategy for item in response.strategies} == {
            "fixed",
            "semantic",
            "structural",
        }
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
        assert {call.args[1] for call in streamed} == {
            "fixed",
            "semantic",
            "structural",
        }
        assert all(call.args[0] == 55 for call in streamed)
        assert all(call.args[3].embedding for call in streamed)

        # Nothing is scored or deleted here: pruning is deferred to /evaluate.
        storage.delete_chunks_except.assert_not_called()
        # The response counts match how many chunks were streamed per strategy.
        streamed_counts = {"fixed": 0, "semantic": 0, "structural": 0}
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
        for strategy in ("fixed", "semantic", "structural"):
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

    def test_uses_the_given_patterns_for_the_structural_candidate(
        self, make_pdf: Callable[[list[str]], bytes]
    ) -> None:
        storage = _fake_storage(document_id=1)

        service.process(
            make_pdf(["Clause 1 Scope.", "Clause 2 Limits."]),
            "report.pdf",
            "analyst",
            structural=StructuralChunkingRequest(
                heading_patterns=[r"^Clause \d+"], min_words=0
            ),
            storage=storage,
        )

        # "Clause N" is no marker of the built-in set, so by default these two
        # pages would be one chunk; the caller's pattern sections them.
        assert [chunk.text for chunk in _stored_chunks(storage, "structural")] == [
            "Clause 1 Scope.",
            "Clause 2 Limits.",
        ]

    def test_an_unidentifiable_type_is_not_chunked_or_persisted(self) -> None:
        storage = MagicMock()

        response = service.process(
            bytes([0, 1, 2]) + b" opaque bytes",
            "mystery.bin",
            "analyst",
            filename="mystery.bin",
            storage=storage,
        )

        assert response.doc_type is DocType.unknown
        assert response.document_id is None
        assert response.strategies == []
        storage.create_document.assert_not_called()
        storage.insert_chunk.assert_not_called()
        storage.delete_chunks_except.assert_not_called()

    @pytest.mark.parametrize(
        ("doc_type", "content", "filename"),
        [
            (
                DocType.html,
                b"<html><body><p>Alpha beta gamma.</p></body></html>",
                "a.html",
            ),
            (DocType.text, b"Alpha beta gamma.", "a.txt"),
        ],
    )
    def test_a_non_pdf_document_is_chunked_and_persisted(
        self, doc_type: DocType, content: bytes, filename: str
    ) -> None:
        storage = _fake_storage()

        response = service.process(
            content, filename, "analyst", filename=filename, storage=storage
        )

        assert response.doc_type is doc_type
        assert response.document_id == 55
        # Every strategy runs on a non-PDF exactly as it does on a PDF -- the
        # format is the extractor's business and nothing downstream's.
        assert {stored.strategy for stored in response.strategies} == {
            "fixed",
            "semantic",
            "structural",
        }
        assert all(stored.chunk_count > 0 for stored in response.strategies)

    def test_a_docx_is_chunked_and_persisted(
        self, make_docx: Callable[[list[str]], bytes]
    ) -> None:
        storage = _fake_storage()

        response = service.process(
            make_docx(["Alpha beta gamma.", "Delta epsilon zeta."]),
            "handbook.docx",
            "analyst",
            filename="handbook.docx",
            storage=storage,
        )

        assert response.doc_type is DocType.docx
        assert all(stored.chunk_count > 0 for stored in response.strategies)

    def test_paginationless_chunks_are_all_attributed_to_page_one(self) -> None:
        storage = _fake_storage()

        service.process(
            b"Alpha beta gamma. " * 200,
            "notes.txt",
            "analyst",
            filename="notes.txt",
            storage=storage,
        )

        # The document has one page, so every chunk cites page 1 rather than a
        # page number the source never had.
        chunks = _stored_chunks(storage)
        assert len(chunks) > 1
        assert {chunk.page_number for chunk in chunks} == {1}

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

    def test_exclusion_applies_to_every_strategy(
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

        # Exclusion happens once, upstream of chunking, so no strategy may see
        # the dropped page -- not just the default "fixed" one.
        for strategy in ("fixed", "semantic", "structural"):
            chunks = _stored_chunks(storage, strategy)
            assert chunks, f"{strategy} stored no chunks"
            assert all(chunk.page_number == 2 for chunk in chunks), strategy
            assert not any("DROPME" in chunk.text for chunk in chunks), strategy
