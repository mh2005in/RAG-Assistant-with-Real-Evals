"""Tests for the Evaluation service.

The service reads a stored document's strategies, retrieves against each for the
caller's question/answer pairs, scores how well the retrievals match the expected
answers, keeps the winner and deletes the losers. Storage is mocked so these stay
offline, and a stub embedder maps text to controlled vectors so the "right"
strategy retrieves the expected answer and clearly wins.

The stub's vectors make the relevance threshold (0.6) easy to reason about: text
matching the expected answer scores 1.0, orthogonal text scores 0.0, and anything
else scores ~0.707 — above the threshold, so "neutral" text still counts as
relevant.
"""

import math
from typing import Any
from unittest.mock import MagicMock

import pytest

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


def _retrieved(strategy: str, text: str, index: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=55,
        document_name="doc.pdf",
        chunking_strategy=strategy,
        chunk_index=index,
        page_number=1,
        text=text,
        score=0.9,
    )


def _ranked(strategy: str, texts: list[str]) -> list[RetrievedChunk]:
    """Retrieved chunks in rank order, best first."""
    return [_retrieved(strategy, text, index) for index, text in enumerate(texts)]


def _request(**overrides: Any) -> EvaluateRequest:
    payload: dict[str, Any] = {
        "document_id": 55,
        "access_role": "analyst",
        "qa_pairs": [{"question": "what do cats do?", "answer": "cats purr"}],
        "top_k": 3,
    }
    payload.update(overrides)
    return EvaluateRequest.model_validate(payload)


def _by_strategy(response: Any) -> dict[str, Any]:
    return {item.strategy: item for item in response.evaluations}


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

    by_strategy = _by_strategy(response)
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

    by_strategy = _by_strategy(response)
    assert by_strategy["semantic"].answer_similarity == 0.0
    assert by_strategy["semantic"].hit_rate == 0.0
    # Its pool did hold a relevant chunk, so recall is a real 0.0 — the retrieval
    # missed something that was there — while nDCG has nothing ranked to score.
    assert by_strategy["semantic"].recall_at_k == 0.0
    assert by_strategy["semantic"].mrr == 0.0
    assert by_strategy["semantic"].ndcg_at_k == 0.0
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


# --- rank-aware metrics (REQ-EVL-04) ----------------------------------------


def test_rank_metrics_separate_strategies_that_answer_similarity_ties() -> None:
    """The point of the rank-aware metrics: same best match, different ranking.

    Both strategies retrieve the same three chunks and both surface the relevant
    one, so answer_similarity, hit_rate and recall@k are identical. Only MRR and
    nDCG see that one of them buried the useful chunk at position 3.
    """
    pool = ["cats purr and nap", "trains run on rails", "trains cross the bridge"]
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {
        "fixed": list(pool),
        "semantic": list(pool),
    }

    def search(*args: Any, **kwargs: Any) -> list[RetrievedChunk]:
        if kwargs["chunking_strategy"] == "fixed":
            return _ranked("fixed", pool)  # relevant chunk first
        return _ranked("semantic", pool[1:] + pool[:1])  # relevant chunk last

    storage.search_chunks.side_effect = search

    by_strategy = _by_strategy(service.evaluate(_request(), storage))
    fixed, semantic = by_strategy["fixed"], by_strategy["semantic"]

    # Indistinguishable on the metrics that existed before.
    assert fixed.answer_similarity == semantic.answer_similarity == 1.0
    assert fixed.hit_rate == semantic.hit_rate == 1.0
    assert fixed.recall_at_k == semantic.recall_at_k == 1.0

    # Told apart by rank: position 1 versus position 3.
    assert fixed.mrr == 1.0
    assert semantic.mrr == pytest.approx(1 / 3, abs=1e-4)
    assert fixed.ndcg_at_k == 1.0
    assert semantic.ndcg_at_k == pytest.approx(1 / math.log2(4))


def test_recall_counts_against_the_whole_pool_not_just_what_was_retrieved() -> None:
    """recall@k is capped by top_k when the document holds more relevant chunks.

    Four chunks in the pool all match the answer but only two slots exist, so a
    retriever that fills both still covers half. Were the denominator the
    retrieved set rather than the pool, this would read a flattering 1.0.
    """
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {
        "fixed": [
            "cats purr softly",
            "cats nap often",
            "cats stretch slowly",
            "cats hunt at dawn",
        ]
    }
    storage.search_chunks.side_effect = lambda *a, **k: _ranked(
        "fixed", ["cats purr softly", "cats nap often"]
    )

    response = service.evaluate(_request(top_k=2), storage)
    fixed = _by_strategy(response)["fixed"]

    assert fixed.recall_at_k == 0.5
    # Both slots held a relevant chunk, so the ordering was as good as it could
    # be — nDCG is 1.0 even though coverage is only half.
    assert fixed.ndcg_at_k == 1.0
    assert fixed.mrr == 1.0


def test_unanswerable_question_reports_null_rather_than_a_zero_score() -> None:
    """A pool with nothing relevant leaves recall and nDCG undefined, not zero.

    The retriever cannot be faulted for failing to surface an answer the document
    does not contain, so those metrics report null while MRR stays a real 0.0.
    """
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {
        "fixed": ["trains run on rails", "trains cross the bridge"]
    }
    storage.search_chunks.side_effect = lambda *a, **k: _ranked(
        "fixed", ["trains run on rails", "trains cross the bridge"]
    )

    response = service.evaluate(_request(), storage)
    fixed = _by_strategy(response)["fixed"]

    assert fixed.recall_at_k is None
    assert fixed.ndcg_at_k is None
    assert fixed.mrr == 0.0
    assert fixed.hit_rate == 0.0


def test_ranking_still_follows_answer_similarity_not_the_rank_metrics() -> None:
    """The winner is unchanged by the new numbers, even when they disagree.

    ``semantic`` ranks its one relevant chunk first (MRR 1.0, nDCG 1.0) and
    ``fixed`` buries its own at position 2 — but ``fixed`` matches the expected
    answer more closely, so it still wins and is still the one kept.
    """
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {
        "fixed": ["trains run on rails", "cats purr and nap"],
        "semantic": ["a quiet afternoon"],
    }

    def search(*args: Any, **kwargs: Any) -> list[RetrievedChunk]:
        if kwargs["chunking_strategy"] == "fixed":
            return _ranked("fixed", ["trains run on rails", "cats purr and nap"])
        return _ranked("semantic", ["a quiet afternoon"])

    storage.search_chunks.side_effect = search

    response = service.evaluate(_request(), storage)
    by_strategy = _by_strategy(response)

    # semantic looks better on every rank-aware metric...
    assert by_strategy["semantic"].mrr > by_strategy["fixed"].mrr
    assert by_strategy["semantic"].ndcg_at_k > by_strategy["fixed"].ndcg_at_k
    # ...but answer_similarity alone decides, so fixed wins and is kept.
    assert by_strategy["fixed"].answer_similarity == 1.0
    assert by_strategy["semantic"].answer_similarity == pytest.approx(0.7071, abs=1e-4)
    assert response.evaluations[0].strategy == "fixed"
    assert response.chunking_strategy == "fixed"
    storage.delete_chunks_except.assert_called_once_with(55, "fixed")


def test_a_chunk_is_embedded_once_per_strategy_not_once_per_question() -> None:
    """Pool vectors are reused for the chunks retrieved out of that pool.

    Scoring embeds the questions, the answers, and each strategy's pool — and
    nothing else, however many questions retrieve the same chunk.
    """
    embedder = MagicMock(wraps=StubEmbedder())
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {"fixed": ["cats purr and nap"]}
    storage.search_chunks.side_effect = lambda *a, **k: _ranked(
        "fixed", ["cats purr and nap"]
    )

    request = _request(
        qa_pairs=[
            {"question": "what do cats do?", "answer": "cats purr"},
            {"question": "how do cats rest?", "answer": "cats nap"},
        ]
    )
    Evaluation(embedder=embedder).evaluate(request, storage)

    embedded = [call.args[0] for call in embedder.embed.call_args_list]
    # Questions, answers, the pool — and no per-question re-embedding of the
    # chunk that both questions retrieved.
    assert embedded == [
        ["what do cats do?", "how do cats rest?"],
        ["cats purr", "cats nap"],
        ["cats purr and nap"],
    ]
