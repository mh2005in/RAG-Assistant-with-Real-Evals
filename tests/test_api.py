"""Endpoint tests for the /process route.

The storage dependency is overridden with a fake so these tests never open a
database connection (see CLAUDE.md); ``fake_storage`` records what would have
been persisted.
"""

from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api import app, get_llm, get_storage
from dtos.responses import RetrievedChunk

client = TestClient(app)


def _stored_text(fake_storage: MagicMock) -> str:
    """All chunk text a mocked storage was streamed.

    The /process response reports which strategies were stored, not the chunks, so
    tests that check *content* inspect what was streamed via ``insert_chunk``
    (called once per chunk as ``insert_chunk(document_id, strategy, index, chunk)``).
    """
    return " ".join(
        call.args[3].text for call in fake_storage.insert_chunk.call_args_list
    )


@pytest.fixture(autouse=True)
def fake_storage() -> Iterator[MagicMock]:
    """Override the storage dependency with a fake for every request."""
    storage = MagicMock()
    storage.create_document.return_value = 123
    app.dependency_overrides[get_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def fake_llm() -> Iterator[MagicMock]:
    """Override the LLM dependency with a fake so no model is called."""
    llm = MagicMock()
    app.dependency_overrides[get_llm] = lambda: llm
    yield llm
    app.dependency_overrides.pop(get_llm, None)


def test_pdf_is_chunked_and_every_strategy_stored(
    make_pdf: Callable[[list[str]], bytes], fake_storage: MagicMock
) -> None:
    pdf = make_pdf(["Page one text.", "Page two text."])
    response = client.post(
        "/process",
        data={
            "name": "report.pdf",
            "access_role": "analyst",
            "chunk_size": "8",
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["doc_type"] == "pdf"
    # The response reports which strategies were stored, not the chunks themselves.
    assert "chunks" not in body
    # Every strategy is chunked and reported; no scoring/winner at process time.
    assert {item["strategy"] for item in body["strategies"]} == {"fixed", "semantic"}
    assert all(item["chunk_count"] > 0 for item in body["strategies"])
    # The document row was created once, and each strategy's chunks streamed in;
    # nothing was pruned.
    assert body["document_id"] == 123
    fake_storage.create_document.assert_called_once_with("report.pdf", "analyst")
    assert {call.args[1] for call in fake_storage.insert_chunk.call_args_list} == {
        "fixed",
        "semantic",
    }
    fake_storage.delete_chunks_except.assert_not_called()


def test_excluded_pages_are_dropped(
    make_pdf: Callable[[list[str]], bytes], fake_storage: MagicMock
) -> None:
    pdf = make_pdf(["KEEPME", "DROPME"])
    response = client.post(
        "/process",
        data={
            "name": "report.pdf",
            "access_role": "analyst",
            "chunk_size": "1000",
            "exclude_pages": "[2]",
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    stored = _stored_text(fake_storage)
    assert "KEEPME" in stored
    assert "DROPME" not in stored


def test_exclude_pages_accepts_mixed_numbers_and_ranges(
    make_pdf: Callable[[list[str]], bytes], fake_storage: MagicMock
) -> None:
    # Regression: the field takes a bare JSON array; a mix of a page number and
    # an inclusive range must be accepted (not "Input should be an object").
    pdf = make_pdf(["ONE", "TWO", "THREE", "FOUR"])
    response = client.post(
        "/process",
        data={
            "name": "report.pdf",
            "access_role": "analyst",
            "chunk_size": "1000",
            "exclude_pages": '[1, {"start": 3, "end": 4}]',
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    stored = _stored_text(fake_storage)
    assert "TWO" in stored
    assert "ONE" not in stored
    assert "THREE" not in stored
    assert "FOUR" not in stored


def test_malformed_exclude_pages_error_names_the_field(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    # The 422 must say which field was malformed, not just the bare pydantic
    # message with no hint of where it came from.
    pdf = make_pdf(["ONE"])
    response = client.post(
        "/process",
        data={
            "name": "report.pdf",
            "access_role": "analyst",
            "chunk_size": "100",
            "exclude_pages": "not json at all",
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][0] == "exclude_pages"


def test_non_positive_chunk_size_is_rejected(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["ONE"])
    response = client.post(
        "/process",
        data={
            "name": "report.pdf",
            "access_role": "analyst",
            "chunk_size": "0",
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 422


def test_page_exclusion_is_optional_and_independent_of_strategy(
    make_pdf: Callable[[list[str]], bytes], fake_storage: MagicMock
) -> None:
    # No exclude_pages field at all: everything is chunked.
    pdf = make_pdf(["KEEPME", "ALSOME"])
    response = client.post(
        "/process",
        data={
            "name": "report.pdf",
            "access_role": "analyst",
            "chunk_size": "1000",
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    stored = _stored_text(fake_storage)
    assert "KEEPME" in stored
    assert "ALSOME" in stored


def test_invalid_page_exclusion_is_rejected(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["anything"])
    response = client.post(
        "/process",
        data={
            "name": "report.pdf",
            "access_role": "analyst",
            "chunk_size": "1000",
            "exclude_pages": "[0]",
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 422


def test_non_pdf_is_detected_but_not_chunked_or_stored(
    fake_storage: MagicMock,
) -> None:
    response = client.post(
        "/process",
        data={
            "name": "notes.txt",
            "access_role": "analyst",
            "chunk_size": "8",
        },
        files={"file": ("notes.txt", b"just some plain text", "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["doc_type"] == "unknown"
    assert body["strategies"] == []
    assert body["document_id"] is None
    fake_storage.create_document.assert_not_called()
    fake_storage.insert_chunk.assert_not_called()


def test_chunk_size_is_optional(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    # No chunk_size: the fixed-size candidate falls back to its default.
    pdf = make_pdf(["Cats purr. Cats nap."])
    response = client.post(
        "/process",
        data={"name": "doc.pdf", "access_role": "analyst"},
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    assert {item["strategy"] for item in response.json()["strategies"]} == {
        "fixed",
        "semantic",
    }


def test_name_and_access_role_are_required(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["anything"])
    response = client.post(
        "/process",
        data={"chunk_size": "8"},
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 422


def test_evaluate_scores_strategies_and_prunes_losers(
    fake_storage: MagicMock,
) -> None:
    # Two strategies stored for the document; /evaluate scores and keeps one.
    fake_storage.read_chunk_texts_by_strategy.return_value = {
        "fixed": ["Cats purr. Cats nap.", "Trains run. Trains are fast."],
        "semantic": ["Cats purr. Cats nap.", "Trains run. Trains are fast."],
    }

    response = client.post(
        "/evaluate",
        json={"document_id": 55, "access_role": "analyst"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == 55
    # Every stored strategy is scored, exactly one selected, best first.
    assert {item["strategy"] for item in body["evaluations"]} == {"fixed", "semantic"}
    selected = [item for item in body["evaluations"] if item["selected"]]
    assert len(selected) == 1
    assert body["chunking_strategy"] == selected[0]["strategy"]
    scores = [item["score"] for item in body["evaluations"]]
    assert scores == sorted(scores, reverse=True)
    # The document was read back under the request's role, and losers pruned.
    fake_storage.read_chunk_texts_by_strategy.assert_called_once_with(55, "analyst")
    fake_storage.delete_chunks_except.assert_called_once_with(
        55, body["chunking_strategy"]
    )


def test_evaluate_404_when_document_has_no_readable_chunks(
    fake_storage: MagicMock,
) -> None:
    # An unknown document, or one under a different role, reads back nothing.
    fake_storage.read_chunk_texts_by_strategy.return_value = {}

    response = client.post(
        "/evaluate",
        json={"document_id": 999, "access_role": "analyst"},
    )

    assert response.status_code == 404
    fake_storage.delete_chunks_except.assert_not_called()


def test_evaluate_requires_document_id_and_access_role() -> None:
    assert client.post("/evaluate", json={"access_role": "analyst"}).status_code == 422
    assert client.post("/evaluate", json={"document_id": 1}).status_code == 422
    # document_id must be a positive id.
    assert (
        client.post(
            "/evaluate", json={"document_id": 0, "access_role": "analyst"}
        ).status_code
        == 422
    )


def test_retrieve_returns_matching_chunks(fake_storage: MagicMock) -> None:
    fake_storage.search_chunks.return_value = [
        RetrievedChunk(
            document_id=1,
            document_name="doc.pdf",
            chunking_strategy="fixed",
            chunk_index=0,
            page_number=2,
            text="the matching chunk",
            score=0.87,
        )
    ]

    response = client.post(
        "/retrieve",
        json={"query": "find the chunk", "access_role": "analyst", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "find the chunk"
    assert body["count"] == 1
    assert body["results"][0]["text"] == "the matching chunk"
    assert body["results"][0]["score"] == 0.87
    # The role and top_k reached the search unchanged.
    _, access_role, top_k, strategy = fake_storage.search_chunks.call_args.args
    assert access_role == "analyst"
    assert top_k == 3
    # No strategy filter requested -> search every strategy.
    assert strategy is None


def test_retrieve_requires_a_query() -> None:
    response = client.post("/retrieve", json={"access_role": "analyst"})

    assert response.status_code == 422


def test_answer_generates_from_retrieved_context(
    fake_storage: MagicMock, fake_llm: MagicMock
) -> None:
    fake_storage.search_chunks.return_value = [
        RetrievedChunk(
            document_id=1,
            document_name="biology.pdf",
            chunking_strategy="fixed",
            chunk_index=0,
            page_number=1,
            text="Plants convert sunlight into energy.",
            score=0.9,
        )
    ]
    fake_llm.generate.return_value = "Plants use photosynthesis [1]."

    response = client.post(
        "/answer",
        json={
            "query": "how do plants get energy",
            "access_role": "student",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "how do plants get energy"
    assert body["answer"] == "Plants use photosynthesis [1]."
    assert body["sources"][0]["text"] == "Plants convert sunlight into energy."
    # The augmented prompt (context + question) reached the model.
    prompt = fake_llm.generate.call_args.args[0]
    assert "Plants convert sunlight into energy." in prompt
    assert "how do plants get energy" in prompt


def test_answer_requires_a_query(fake_llm: MagicMock) -> None:
    response = client.post("/answer", json={"access_role": "student"})

    assert response.status_code == 422
