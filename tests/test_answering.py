"""Tests for the Answering service.

Retrieval uses the fake embedder (conftest autouse); the storage and the LLM are
mocked, so these run offline.
"""

from unittest.mock import MagicMock

from dtos.requests import AnswerRequest
from dtos.responses import RetrievedChunk
from services.answering import Answering


def _chunk(text: str, page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=1,
        document_name="doc.pdf",
        chunk_index=0,
        page_number=page,
        text=text,
        score=0.9,
    )


def test_answer_builds_augmented_prompt_and_returns_sources() -> None:
    storage = MagicMock()
    storage.search_chunks.return_value = [
        _chunk("Photosynthesis converts sunlight.", page=1),
        _chunk("Mitochondria make ATP.", page=2),
    ]
    llm = MagicMock()
    llm.generate.return_value = "Plants use photosynthesis [1]."

    request = AnswerRequest(
        query="How do plants get energy?", access_role="student", top_k=2
    )
    response = Answering().answer(request, storage, llm)

    # The prompt carries the question and the numbered, cited context.
    prompt = llm.generate.call_args.args[0]
    assert "How do plants get energy?" in prompt
    assert "[1] (doc.pdf, p.1) Photosynthesis converts sunlight." in prompt
    assert "[2] (doc.pdf, p.2) Mitochondria make ATP." in prompt

    assert response.answer == "Plants use photosynthesis [1]."
    assert [s.text for s in response.sources] == [
        "Photosynthesis converts sunlight.",
        "Mitochondria make ATP.",
    ]
    # Retrieval was scoped to the requested role and top_k.
    _, access_role, top_k = storage.search_chunks.call_args.args
    assert access_role == "student"
    assert top_k == 2


def test_answer_with_no_context_skips_the_model() -> None:
    storage = MagicMock()
    storage.search_chunks.return_value = []
    llm = MagicMock()

    response = Answering().answer(
        AnswerRequest(query="anything", access_role="student"), storage, llm
    )

    assert response.sources == []
    assert "couldn't find" in response.answer
    llm.generate.assert_not_called()
