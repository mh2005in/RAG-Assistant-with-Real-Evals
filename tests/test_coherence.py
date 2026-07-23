"""Tests for the label-free chunking quality score.

A stub embedder returns hand-picked vectors so cohesion and separation are
deterministic; nothing hits a model.
"""

import pytest

from dtos.responses import Chunk
from services.chunking import score_chunks

# Two orthogonal "topics".
_X = [1.0, 0.0]
_Y = [0.0, 1.0]


class StubEmbedder:
    """Maps each sentence to a canned vector by lookup."""

    def __init__(self, by_sentence: dict[str, list[float]]) -> None:
        self._by_sentence = by_sentence

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._by_sentence[text] for text in texts]

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:  # pragma: no cover
        raise NotImplementedError


_VECTORS = {
    "Cats purr.": _X,
    "Cats nap.": _X,
    "Trains run.": _Y,
    "Trains are fast.": _Y,
}


def test_clean_split_scores_above_a_mixed_split() -> None:
    embedder = StubEmbedder(_VECTORS)

    # Chunks aligned with the topics: each is internally identical, and the two
    # are orthogonal to each other.
    clean = score_chunks(
        ["Cats purr. Cats nap.", "Trains run. Trains are fast."], embedder
    )
    # Chunks straddling the topic boundary: each mixes both topics.
    mixed = score_chunks(
        ["Cats purr. Trains run.", "Cats nap. Trains are fast."], embedder
    )

    clean_cohesion, clean_separation, clean_score = clean
    assert clean_cohesion == pytest.approx(1.0)
    assert clean_separation == pytest.approx(0.0)
    assert clean_score == pytest.approx(1.0)
    # The mixed split is strictly worse on every axis that matters.
    assert mixed[0] < clean_cohesion
    assert mixed[1] > clean_separation
    assert mixed[2] < clean_score


def test_over_splitting_is_punished_by_separation() -> None:
    embedder = StubEmbedder(_VECTORS)

    # Every sentence its own chunk: perfectly "cohesive" but neighbours from the
    # same topic are identical, so separation is high and the score suffers.
    over_split = score_chunks(
        ["Cats purr.", "Cats nap.", "Trains run.", "Trains are fast."], embedder
    )
    good = score_chunks(
        ["Cats purr. Cats nap.", "Trains run. Trains are fast."], embedder
    )

    assert over_split[0] == pytest.approx(1.0)  # trivially cohesive
    assert over_split[1] > good[1]  # but neighbours are too alike
    assert over_split[2] < good[2]


def test_single_chunk_scores_zero_not_a_free_win() -> None:
    embedder = StubEmbedder(_VECTORS)

    cohesion, separation, score = score_chunks(
        ["Cats purr. Cats nap. Trains run. Trains are fast."], embedder
    )

    # A single chunk has no neighbour, so separation is vacuously 0. Scoring it
    # 0.0 stops "don't chunk at all" from beating every real split.
    assert separation == 0.0
    assert score == 0.0
    assert cohesion > 0.0

    split = score_chunks(
        ["Cats purr. Cats nap.", "Trains run. Trains are fast."], embedder
    )
    assert split[2] > score


def test_no_chunks_scores_zero() -> None:
    assert score_chunks([], StubEmbedder({})) == (0.0, 0.0, 0.0)
    assert score_chunks(["", "   "], StubEmbedder({})) == (0.0, 0.0, 0.0)


def test_chunk_without_terminator_still_counts_as_a_sentence() -> None:
    embedder = StubEmbedder({"no full stop here": _X, "Trains run.": _Y})

    cohesion, _, _ = score_chunks(["no full stop here", "Trains run."], embedder)

    # Both chunks were scored (a chunk with no '.' must not silently vanish).
    assert cohesion == pytest.approx(1.0)
