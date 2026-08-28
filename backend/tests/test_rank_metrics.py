"""Tests for the rank-aware retrieval metrics.

Pure arithmetic over binary relevance labels, so every expected value here is
hand-computed rather than read back from the implementation. The discount is
``1 / log2(rank + 1)`` with 1-based ranks, which makes the useful constants
``log2(2) = 1`` (rank 1), ``log2(3) ~ 1.585`` (rank 2) and ``log2(4) = 2``
(rank 3).
"""

import math

import pytest

from services.rank_metrics import ndcg_at_k, recall_at_k, reciprocal_rank

# Gain of a relevant chunk at rank 2 and rank 3, used to build expected nDCG.
_RANK_2_GAIN = 1 / math.log2(3)
_RANK_3_GAIN = 1 / math.log2(4)


class TestRecallAtK:
    def test_counts_retrieved_relevant_against_the_whole_pool(self) -> None:
        # Two of the pool's four relevant chunks were retrieved.
        assert recall_at_k([True, False, True], relevant_total=4) == 0.5

    def test_caps_below_one_when_the_pool_holds_more_than_k(self) -> None:
        # A perfect retriever with only two slots still cannot cover five
        # relevant chunks — that is the honest reading of recall *at k*.
        assert recall_at_k([True, True], relevant_total=5) == pytest.approx(0.4)

    def test_full_coverage_scores_one(self) -> None:
        assert recall_at_k([True, True], relevant_total=2) == 1.0

    def test_retrieving_nothing_relevant_scores_zero(self) -> None:
        assert recall_at_k([False, False], relevant_total=3) == 0.0

    def test_empty_retrieval_scores_zero(self) -> None:
        assert recall_at_k([], relevant_total=3) == 0.0

    def test_is_undefined_when_the_pool_holds_nothing_relevant(self) -> None:
        # Nothing could have been found, so this is the absence of a score, not a
        # score of zero — the caller skips the question rather than penalising it.
        assert recall_at_k([False], relevant_total=0) is None


class TestReciprocalRank:
    @pytest.mark.parametrize(
        ("relevance", "expected"),
        [
            ([True, False, False], 1.0),
            ([False, True, False], 0.5),
            ([False, False, True], 1 / 3),
        ],
    )
    def test_is_the_inverse_of_the_first_relevant_position(
        self, relevance: list[bool], expected: float
    ) -> None:
        assert reciprocal_rank(relevance) == pytest.approx(expected)

    def test_only_the_first_relevant_chunk_counts(self) -> None:
        assert reciprocal_rank([False, True, True]) == 0.5

    @pytest.mark.parametrize("relevance", [[], [False, False]])
    def test_never_reaching_a_relevant_chunk_scores_zero(
        self, relevance: list[bool]
    ) -> None:
        assert reciprocal_rank(relevance) == 0.0


class TestNdcgAtK:
    def test_the_ideal_ordering_scores_one(self) -> None:
        assert ndcg_at_k([True, True], relevant_total=2) == 1.0

    def test_a_later_hit_is_discounted(self) -> None:
        # One relevant chunk at rank 2: DCG = 1/log2(3), ideal = 1/log2(2) = 1.
        assert ndcg_at_k([False, True], relevant_total=1) == pytest.approx(_RANK_2_GAIN)

    def test_rewards_ranking_every_relevant_chunk_early(self) -> None:
        # Hits at ranks 1 and 3 against an ideal of ranks 1 and 2.
        expected = (1 + _RANK_3_GAIN) / (1 + _RANK_2_GAIN)
        assert ndcg_at_k([True, False, True], relevant_total=2) == pytest.approx(
            expected
        )

    def test_ideal_is_capped_by_the_list_length(self) -> None:
        # Five relevant chunks in the pool but only two slots: filling both is
        # still a perfect ordering, so nDCG is 1.0 even though recall is 0.4.
        assert ndcg_at_k([True, True], relevant_total=5) == 1.0
        assert recall_at_k([True, True], relevant_total=5) == pytest.approx(0.4)

    def test_retrieving_nothing_relevant_scores_zero(self) -> None:
        assert ndcg_at_k([False, False], relevant_total=5) == 0.0

    def test_empty_retrieval_scores_zero(self) -> None:
        # No ordering of an empty list beats any other, so there is nothing to
        # normalise against.
        assert ndcg_at_k([], relevant_total=3) == 0.0

    def test_is_undefined_when_the_pool_holds_nothing_relevant(self) -> None:
        assert ndcg_at_k([True], relevant_total=0) is None
