"""Tests for the semantic chunker.

A stub embedder returns hand-picked vectors so the sentence distances — and
therefore the breakpoints — are deterministic. Nothing hits a model.
"""

import pytest

from dtos.responses import Chunk
from services.chunking import SemanticChunker
from services.chunking.semantic import _cosine_distance, _percentile
from services.chunking.sentences import split_sentences


class StubEmbedder:
    """Returns a canned vector per text, in order."""

    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors
        self.embedded: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded = list(texts)
        return self._vectors[: len(texts)]

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:  # pragma: no cover
        raise NotImplementedError


# Two "topics": X-ish vectors then Y-ish vectors, so the jump sits in the middle.
_X = [1.0, 0.0]
_Y = [0.0, 1.0]


def test_splits_at_the_semantic_shift() -> None:
    pages = ["Cats purr. Cats nap. Trains are fast. Trains carry freight."]
    embedder = StubEmbedder([_X, _X, _Y, _Y])

    chunks = SemanticChunker(embedder).chunk(pages)

    assert chunks == ["Cats purr. Cats nap.", "Trains are fast. Trains carry freight."]


def test_uniform_text_stays_one_chunk() -> None:
    # No distance stands out, so there is no topic shift to break on.
    pages = ["Cats purr. Cats nap. Cats stretch."]
    embedder = StubEmbedder([_X, _X, _X])

    assert SemanticChunker(embedder).chunk(pages) == [
        "Cats purr. Cats nap. Cats stretch."
    ]


def test_chunk_with_pages_tags_the_starting_page() -> None:
    pages = ["Cats purr. Cats nap.", "Trains are fast. Trains carry freight."]
    embedder = StubEmbedder([_X, _X, _Y, _Y])

    assert SemanticChunker(embedder).chunk_with_pages(pages) == [
        (1, "Cats purr. Cats nap."),
        (2, "Trains are fast. Trains carry freight."),
    ]


def test_blank_pages_are_skipped_without_shifting_page_numbers() -> None:
    # Page 1 was excluded upstream, so it arrives blank; page 2 keeps its number.
    pages = ["", "Cats purr. Cats nap."]
    embedder = StubEmbedder([_X, _X])

    assert SemanticChunker(embedder).chunk_with_pages(pages) == [
        (2, "Cats purr. Cats nap.")
    ]


def test_no_text_yields_no_chunks() -> None:
    embedder = StubEmbedder([])

    assert SemanticChunker(embedder).chunk([]) == []
    assert SemanticChunker(embedder).chunk(["", "   "]) == []


def test_single_sentence_is_one_chunk_without_embedding() -> None:
    embedder = StubEmbedder([])

    assert SemanticChunker(embedder).chunk(["Only one sentence here."]) == [
        "Only one sentence here."
    ]
    # Nothing to compare, so the embedder is never called.
    assert embedder.embedded == []


def test_embeds_each_sentence_once() -> None:
    embedder = StubEmbedder([_X, _X, _Y, _Y])

    SemanticChunker(embedder).chunk(
        ["Cats purr. Cats nap. Trains are fast. Trains go."]
    )

    assert embedder.embedded == [
        "Cats purr.",
        "Cats nap.",
        "Trains are fast.",
        "Trains go.",
    ]


class TestHelpers:
    def test_sentences_splits_on_terminators_and_strips(self) -> None:
        assert split_sentences("One. Two!  Three?\nFour.") == [
            "One.",
            "Two!",
            "Three?",
            "Four.",
        ]

    def test_sentences_ignores_blank_text(self) -> None:
        assert split_sentences("   \n ") == []

    def test_cosine_distance_bounds(self) -> None:
        assert _cosine_distance(_X, _X) == 0.0
        assert _cosine_distance(_X, _Y) == 1.0
        # A zero vector has no direction; treat it as maximally distant.
        assert _cosine_distance(_X, [0.0, 0.0]) == 1.0

    def test_percentile_interpolates(self) -> None:
        assert _percentile([1.0], 95) == 1.0
        assert _percentile([0.0, 1.0], 50) == 0.5
        assert _percentile([0.0, 0.0, 1.0], 95) == pytest.approx(0.9)
