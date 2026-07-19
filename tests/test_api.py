"""Endpoint tests for the /process route.

The storage dependency is overridden with a fake so these tests never open a
database connection (see CLAUDE.md); ``fake_storage`` records what would have
been persisted.
"""

from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api import app, get_storage
from dtos.responses import RetrievedChunk, StoredDocument

client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_storage() -> Iterator[MagicMock]:
    """Override the storage dependency with a fake for every request."""
    storage = MagicMock()
    storage.insert_document.return_value = StoredDocument(
        document_id=123, chunk_count=1
    )
    app.dependency_overrides[get_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_storage, None)


def test_pdf_is_chunked_and_stored_with_fixed_strategy(
    make_pdf: Callable[[list[str]], bytes], fake_storage: MagicMock
) -> None:
    pdf = make_pdf(["Page one text.", "Page two text."])
    response = client.post(
        "/process",
        data={
            "strategy": "fixed",
            "name": "report.pdf",
            "access_role": "analyst",
            "fixed_size": '{"chunk_size": 8}',
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["doc_type"] == "pdf"
    assert body["chunk_count"] == len(body["chunks"])
    assert body["chunk_count"] > 0
    # Fixed-size chunks are capped at chunk_size words.
    assert all(len(chunk["text"].split()) <= 8 for chunk in body["chunks"])
    # Each chunk is serialized with its stats and a non-empty embedding.
    first = body["chunks"][0]
    assert first["page_number"] >= 1
    assert first["page_char_count"] == len(first["text"])
    assert isinstance(first["embedding"], list) and first["embedding"]
    # The document was persisted and its id returned.
    assert body["document_id"] == 123
    name, access_role, _ = fake_storage.insert_document.call_args.args
    assert name == "report.pdf"
    assert access_role == "analyst"


def test_excluded_pages_are_dropped(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["KEEPME", "DROPME"])
    response = client.post(
        "/process",
        data={
            "strategy": "fixed",
            "name": "report.pdf",
            "access_role": "analyst",
            "fixed_size": '{"chunk_size": 1000, "exclude_pages": [2]}',
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    joined = "".join(chunk["text"] for chunk in response.json()["chunks"])
    assert "KEEPME" in joined
    assert "DROPME" not in joined


def test_non_pdf_is_detected_but_not_chunked_or_stored(
    fake_storage: MagicMock,
) -> None:
    response = client.post(
        "/process",
        data={
            "strategy": "fixed",
            "name": "notes.txt",
            "access_role": "analyst",
            "fixed_size": '{"chunk_size": 8}',
        },
        files={"file": ("notes.txt", b"just some plain text", "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["doc_type"] == "unknown"
    assert body["chunks"] == []
    assert body["chunk_count"] == 0
    assert body["document_id"] is None
    fake_storage.insert_document.assert_not_called()


def test_fixed_strategy_requires_fixed_size(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["anything"])
    response = client.post(
        "/process",
        data={"strategy": "fixed", "name": "doc.pdf", "access_role": "analyst"},
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 422


def test_name_and_access_role_are_required(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["anything"])
    response = client.post(
        "/process",
        data={"strategy": "fixed", "fixed_size": '{"chunk_size": 8}'},
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 422


def test_retrieve_returns_matching_chunks(fake_storage: MagicMock) -> None:
    fake_storage.search_chunks.return_value = [
        RetrievedChunk(
            document_id=1,
            document_name="doc.pdf",
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
    _, access_role, top_k = fake_storage.search_chunks.call_args.args
    assert access_role == "analyst"
    assert top_k == 3


def test_retrieve_requires_a_query() -> None:
    response = client.post("/retrieve", json={"access_role": "analyst"})

    assert response.status_code == 422
