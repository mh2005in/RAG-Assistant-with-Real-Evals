"""Tests for the Evaluation service.

The service reads a stored document's strategies, retrieves against each for the
caller's question/answer pairs, scores how well the retrievals match the expected
answers, keeps the winner and deletes the losers. Storage is mocked so these stay
offline, and a stub embedder maps text to controlled vectors so the "right"
strategy retrieves the expected answer and clearly wins.
"""

from typing import Any
from unittest.mock import MagicMock

from dtos.requests import EvaluateRequest
from dtos.responses import Chunk, RetrievedChunk
from services.evaluation import Evaluation


class StubEmbedder:
    """Deterministic embedder: text about cats -> [1, 0], trains -> [0, 1].

    Lets a test make one strategy's retrieval match the expected answer (high
    cosine similarity) and another's miss it (orthogonal), without any model.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(text) for text in texts]

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        return [
            chunk.model_copy(update={"embedding": self._vec(chunk.text)})
            for chunk in chunks
        ]

    @staticmethod
    def _vec(text: str) -> list[float]:
        lowered = text.lower()
        if "cat" in lowered or "purr" in lowered:
            return [1.0, 0.0]
        if "train" in lowered:
            return [0.0, 1.0]
        return [0.5, 0.5]


def _retrieved(strategy: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=55,
        document_name="doc.pdf",
        chunking_strategy=strategy,
        chunk_index=0,
        page_number=1,
        text=text,
        score=0.9,
    )


def _request(**overrides: Any) -> EvaluateRequest:
    payload: dict[str, Any] = {
        "document_id": 55,
        "access_role": "analyst",
        "qa_pairs": [{"question": "what do cats do?", "answer": "cats purr"}],
        "top_k": 3,
    }
    payload.update(overrides)
    return EvaluateRequest.model_validate(payload)


service = Evaluation(embedder=StubEmbedder())


def test_ranks_strategies_by_answer_match_and_prunes_losers() -> None:
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {
        "fixed": ["cats purr and nap"],
        "semantic": ["trains run on rails"],
    }

    # fixed retrieves the cat chunk (matches the answer); semantic retrieves a
    # train chunk (orthogonal to the answer).
    def search(*args: Any, **kwargs: Any) -> list[RetrievedChunk]:
        if kwargs["chunking_strategy"] == "fixed":
            return [_retrieved("fixed", "Cats purr and nap in the sun.")]
        return [_retrieved("semantic", "Trains run on steel rails.")]

    storage.search_chunks.side_effect = search

    response = service.evaluate(_request(), storage)

    assert response.document_id == 55
    # Both strategies scored; the one that retrieved the answer wins and is first.
    assert {item.strategy for item in response.evaluations} == {"fixed", "semantic"}
    assert response.chunking_strategy == "fixed"
    assert response.evaluations[0].strategy == "fixed"
    assert response.evaluations[0].selected is True

    by_strategy = {item.strategy: item for item in response.evaluations}
    assert (
        by_strategy["fixed"].answer_similarity
        > by_strategy["semantic"].answer_similarity
    )
    assert by_strategy["fixed"].answer_similarity == 1.0
    assert by_strategy["fixed"].hit_rate == 1.0
    assert by_strategy["semantic"].hit_rate == 0.0
    assert all(item.questions == 1 for item in response.evaluations)

    # Read under the request's role; retrieval confined to this document and
    # strategy, at the requested top_k; then losers pruned.
    storage.read_chunk_texts_by_strategy.assert_called_once_with(55, "analyst")
    for call in storage.search_chunks.call_args_list:
        assert call.kwargs["document_id"] == 55
        assert call.args[1:] == ("analyst", 3)
    assert {
        call.kwargs["chunking_strategy"]
        for call in storage.search_chunks.call_args_list
    } == {
        "fixed",
        "semantic",
    }
    storage.delete_chunks_except.assert_called_once_with(55, "fixed")


def test_strategy_that_retrieves_nothing_scores_zero() -> None:
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {
        "fixed": ["cats purr"],
        "semantic": ["cats nap"],
    }

    def search(*args: Any, **kwargs: Any) -> list[RetrievedChunk]:
        if kwargs["chunking_strategy"] == "fixed":
            return [_retrieved("fixed", "Cats purr when content.")]
        return []  # semantic retrieves nothing

    storage.search_chunks.side_effect = search

    response = service.evaluate(_request(), storage)

    by_strategy = {item.strategy: item for item in response.evaluations}
    assert by_strategy["semantic"].answer_similarity == 0.0
    assert by_strategy["semantic"].hit_rate == 0.0
    assert response.chunking_strategy == "fixed"


def test_no_chunks_yields_empty_response_and_no_pruning() -> None:
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {}

    response = service.evaluate(_request(document_id=999), storage)

    assert response.document_id == 999
    assert response.chunking_strategy is None
    assert response.evaluations == []
    storage.search_chunks.assert_not_called()
    storage.delete_chunks_except.assert_not_called()
