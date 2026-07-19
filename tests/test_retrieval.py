"""Tests for the Retrieval service.

The embedder is the fake from conftest (autouse), so these run offline; the
storage is mocked so no database is touched.
"""

from unittest.mock import MagicMock

from dtos.requests import RetrievalRequest
from dtos.responses import RetrievedChunk
from services.retrieval import Retrieval


def _retrieved(text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=1,
        document_name="doc.pdf",
        chunk_index=0,
        page_number=1,
        text=text,
        score=score,
    )


def test_retrieve_embeds_query_then_searches() -> None:
    storage = MagicMock()
    storage.search_chunks.return_value = [_retrieved("alpha", 0.9)]

    request = RetrievalRequest(query="find alpha", access_role="analyst", top_k=3)
    response = Retrieval().retrieve(request, storage)

    # The query text is embedded (fake embedder -> [len(text), 0.0]) and the
    # vector, role, and top_k are passed straight to the storage search.
    embedding, access_role, top_k = storage.search_chunks.call_args.args
    assert embedding == [float(len("find alpha")), 0.0]
    assert access_role == "analyst"
    assert top_k == 3

    assert response.query == "find alpha"
    assert response.count == 1
    assert response.results[0].text == "alpha"


def test_retrieve_with_no_matches_returns_empty() -> None:
    storage = MagicMock()
    storage.search_chunks.return_value = []

    response = Retrieval().retrieve(
        RetrievalRequest(query="nothing", access_role="analyst"), storage
    )

    assert response.count == 0
    assert response.results == []
