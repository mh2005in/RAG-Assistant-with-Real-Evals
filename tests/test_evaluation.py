"""Tests for the Evaluation service.

The service reads a stored document's chunks back, scores every strategy, keeps
the winner and deletes the losers. Storage is mocked so these stay offline, and
the autouse ``fake_embedder`` fixture keeps the coherence scoring off the network
(see CLAUDE.md).
"""

from unittest.mock import MagicMock

from dtos.requests import EvaluateRequest
from services.evaluation import Evaluation

service = Evaluation()


def test_scores_every_strategy_selects_a_winner_and_prunes() -> None:
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {
        "fixed": ["Cats purr. Cats nap.", "Trains run. Trains are fast."],
        "semantic": ["Cats purr. Cats nap.", "Trains run. Trains are fast."],
    }

    response = service.evaluate(
        EvaluateRequest(document_id=55, access_role="analyst"), storage
    )

    assert response.document_id == 55
    # Every stored strategy is scored; exactly one is selected as the winner.
    assert {item.strategy for item in response.evaluations} == {"fixed", "semantic"}
    selected = [item for item in response.evaluations if item.selected]
    assert len(selected) == 1
    assert response.chunking_strategy == selected[0].strategy

    # Evaluations are ordered best first, and the winner tops the list.
    scores = [item.score for item in response.evaluations]
    assert scores == sorted(scores, reverse=True)
    assert selected[0] is response.evaluations[0]
    assert selected[0].chunk_count == 2

    # The document was read under the request's role, and losers were pruned.
    storage.read_chunk_texts_by_strategy.assert_called_once_with(55, "analyst")
    storage.delete_chunks_except.assert_called_once_with(55, response.chunking_strategy)


def test_no_chunks_yields_empty_response_and_no_pruning() -> None:
    storage = MagicMock()
    storage.read_chunk_texts_by_strategy.return_value = {}

    response = service.evaluate(
        EvaluateRequest(document_id=999, access_role="analyst"), storage
    )

    assert response.document_id == 999
    assert response.chunking_strategy is None
    assert response.evaluations == []
    # Nothing to score means nothing is deleted.
    storage.delete_chunks_except.assert_not_called()
