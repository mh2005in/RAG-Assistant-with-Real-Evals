"""Endpoint tests for the /process route."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_pdf_is_chunked_with_fixed_strategy(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["Page one text.", "Page two text."])
    response = client.post(
        "/process",
        data={"strategy": "fixed", "fixed_size": '{"chunk_size": 8}'},
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["doc_type"] == "pdf"
    assert body["chunk_count"] == len(body["chunks"])
    assert body["chunk_count"] > 0
    # Fixed-size chunks are capped at chunk_size characters.
    assert all(len(chunk) <= 8 for chunk in body["chunks"])


def test_excluded_pages_are_dropped(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["KEEPME", "DROPME"])
    response = client.post(
        "/process",
        data={
            "strategy": "fixed",
            "fixed_size": '{"chunk_size": 1000, "exclude_pages": [2]}',
        },
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    joined = "".join(response.json()["chunks"])
    assert "KEEPME" in joined
    assert "DROPME" not in joined


def test_non_pdf_is_detected_but_not_chunked() -> None:
    response = client.post(
        "/process",
        data={"strategy": "fixed", "fixed_size": '{"chunk_size": 8}'},
        files={"file": ("notes.txt", b"just some plain text", "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["doc_type"] == "unknown"
    assert body["chunks"] == []
    assert body["chunk_count"] == 0


def test_fixed_strategy_requires_fixed_size(
    make_pdf: Callable[[list[str]], bytes],
) -> None:
    pdf = make_pdf(["anything"])
    response = client.post(
        "/process",
        data={"strategy": "fixed"},
        files={"file": ("doc.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 422
