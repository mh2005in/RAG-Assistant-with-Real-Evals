"""Tests for the answer-faithfulness metric.

A stub embedder maps text to hand-picked orthogonal vectors, so support is
exactly 1.0 or 0.0 and every score is deterministic; nothing hits a model. The
stub looks its input up by exact string, which also pins what the metric embeds:
a claim reaches it with its citation markers already stripped.
"""

import pytest

from dtos.responses import Chunk
from services.generation import score_answer

# Two orthogonal "topics": a claim about one is perfectly supported by context on
# the same topic (cosine 1.0) and not at all by the other (cosine 0.0).
_X = [1.0, 0.0]
_Y = [0.0, 1.0]

_CHUNK_X = "Chunking decides what the retriever can find."
_CHUNK_Y = "Postgres stores the vectors."

# Claims as the metric sees them: one sentence, no citation markers left.
_CLAIM_X = "Chunking decides what the retriever finds."
_CLAIM_Y = "The store is written in Rust."

# A chunk holding both topics: matched whole it would look like neither, which
# is why the metric compares a claim against a chunk's sentences.
_MIXED_CHUNK = f"{_CHUNK_Y} {_CHUNK_X}"

_VECTORS = {
    _CHUNK_X: _X,
    _CHUNK_Y: _Y,
    _CLAIM_X: _X,
    _CLAIM_Y: _Y,
}


class StubEmbedder:
    """Maps each text to a canned vector by lookup."""

    def __init__(self, by_text: dict[str, list[float]]) -> None:
        self._by_text = by_text

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._by_text[text] for text in texts]

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:  # pragma: no cover
        raise NotImplementedError


def _embedder() -> StubEmbedder:
    return StubEmbedder(_VECTORS)


def test_a_grounded_answer_scores_above_an_ungrounded_one() -> None:
    """The metric's whole job: telling those two apart."""
    grounded = score_answer(_CLAIM_X, [_CHUNK_X], _embedder())
    ungrounded = score_answer(_CLAIM_Y, [_CHUNK_X], _embedder())

    assert grounded.faithfulness == 1.0
    assert grounded.mean_support == pytest.approx(1.0)
    assert ungrounded.faithfulness == 0.0
    assert ungrounded.mean_support == pytest.approx(0.0)


def test_each_sentence_is_scored_as_its_own_claim() -> None:
    score = score_answer(f"{_CLAIM_X} {_CLAIM_Y}", [_CHUNK_X], _embedder())

    # One claim is backed by the context and one is invented: half the answer.
    assert score.claims == 2
    assert score.faithfulness == 0.5
    assert [support.supported for support in score.supports] == [True, False]


def test_citations_are_stripped_before_the_claim_is_embedded() -> None:
    """``[1, 2]`` is punctuation, not content -- it must not reach the embedder.

    Stripping also has to close the gap the marker leaves, or the claim would be
    embedded as "finds ." and no longer match the sentence it came from.
    """
    score = score_answer(
        "Chunking decides what the retriever finds [1, 2].",
        [_CHUNK_X, _CHUNK_Y],
        _embedder(),
    )

    assert score.supports[0].claim == _CLAIM_X
    assert score.supports[0].citations == [1, 2]
    assert score.faithfulness == 1.0


def test_a_citation_naming_a_chunk_that_was_never_in_context_is_invalid() -> None:
    score = score_answer(
        "Chunking decides what the retriever finds [4].", [_CHUNK_X], _embedder()
    )

    assert score.supports[0].invalid_citations == [4]
    assert score.citation_validity == 0.0
    # Nothing valid was cited, so there is no cited chunk to score against.
    assert score.cited_support is None
    # The claim is still grounded -- citing badly is a separate failure.
    assert score.faithfulness == 1.0


def test_citing_the_wrong_source_is_caught_even_when_the_claim_is_grounded() -> None:
    """The failure a support-only metric waves through."""
    score = score_answer(
        "Chunking decides what the retriever finds [2].",
        [_CHUNK_X, _CHUNK_Y],
        _embedder(),
    )

    # Chunk 1 backs the claim, so support is perfect and the citation is in range.
    assert score.faithfulness == 1.0
    assert score.citation_validity == 1.0
    assert score.supports[0].best_chunk == 1
    # But the chunk it actually cited says nothing of the sort.
    assert score.cited_support == pytest.approx(0.0)


def test_citation_coverage_counts_the_claims_that_cite_anything() -> None:
    score = score_answer(
        f"Chunking decides what the retriever finds [1]. {_CLAIM_Y}",
        [_CHUNK_X],
        _embedder(),
    )

    assert score.citation_coverage == 0.5
    assert score.citation_validity == 1.0


def test_an_answer_with_no_context_to_ground_on_scores_zero() -> None:
    score = score_answer(_CLAIM_X, [], _embedder())

    assert score.claims == 1
    assert score.faithfulness == 0.0
    assert score.supports == []


def test_an_empty_answer_has_nothing_to_score() -> None:
    score = score_answer("   ", [_CHUNK_X], _embedder())

    assert score.claims == 0
    assert score.faithfulness == 0.0
    assert score.citation_validity is None


def test_a_claim_is_matched_against_a_sentence_not_the_whole_chunk() -> None:
    """Chunk-level matching could not separate grounded from ungrounded answers.

    The stub gives every sentence its own vector, so a chunk that mixes topics can
    only score 1.0 if the claim was compared against the sentence inside it.
    """
    score = score_answer(_CLAIM_X, [_CHUNK_Y, _MIXED_CHUNK], _embedder())

    assert score.mean_support == pytest.approx(1.0)
    # And the sentence still reports the chunk it belongs to, so citations of
    # chunk 2 can be scored against it.
    assert score.supports[0].best_chunk == 2
