"""Semantic chunking strategy (chunking stage).

Splits pages into sentences, embeds each sentence, and starts a new chunk wherever
consecutive sentences are semantically far apart — so chunk boundaries fall at
topic shifts instead of an arbitrary word count.

The breakpoint threshold is the ``breakpoint_percentile`` of the observed
consecutive-sentence distances, which adapts to the document: a document with one
sharp topic shift breaks there, a uniform one stays whole. That keeps the strategy
parameter-free from the caller's point of view — page exclusion (applied upstream)
is its only input.

Embedding sentences costs an extra embedding pass over the document; that is
inherent to the strategy, and the resulting chunks are embedded again downstream.
"""

import math

from services.chunking.sentences import split_sentences
from services.embedding import Embedder

# Distances above this percentile of all consecutive-sentence distances are
# treated as topic shifts. 95 keeps breaks rare, so chunks stay coherent.
_DEFAULT_BREAKPOINT_PERCENTILE = 95.0


def _cosine_distance(left: list[float], right: list[float]) -> float:
    """Cosine distance (``1 - similarity``) between two vectors."""
    dot = sum(x * y for x, y in zip(left, right))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(y * y for y in right))
    if left_norm == 0.0 or right_norm == 0.0:
        # A zero vector has no direction; treat it as maximally distant.
        return 1.0
    return 1.0 - dot / (left_norm * right_norm)


def _percentile(values: list[float], percentile: float) -> float:
    """Linearly-interpolated percentile of ``values`` (which must be non-empty)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class SemanticChunker:
    """Group consecutive sentences into chunks, breaking at semantic shifts.

    Needs an :class:`~services.embedding.Embedder` to score sentence similarity;
    pass a fake in tests to keep them offline and deterministic.
    """

    def __init__(
        self,
        embedder: Embedder,
        breakpoint_percentile: float = _DEFAULT_BREAKPOINT_PERCENTILE,
    ) -> None:
        self._embedder = embedder
        self._breakpoint_percentile = breakpoint_percentile

    def chunk(self, pages: list[str]) -> list[str]:
        return [text for _, text in self.chunk_with_pages(pages)]

    def chunk_with_pages(self, pages: list[str]) -> list[tuple[int, str]]:
        """Group sentences into chunks, tagging each with its start page.

        A chunk can span a page boundary; the reported page is the one containing
        the chunk's first sentence.
        """
        # Flatten pages into (sentence, source page) pairs. An excluded page
        # arrives blank and contributes nothing.
        sentences: list[tuple[str, int]] = []
        for page_number, text in enumerate(pages, start=1):
            sentences.extend(
                (sentence, page_number) for sentence in split_sentences(text)
            )

        if not sentences:
            return []
        if len(sentences) == 1:
            return [(sentences[0][1], sentences[0][0])]

        vectors = self._embedder.embed([sentence for sentence, _ in sentences])
        distances = [
            _cosine_distance(vectors[index], vectors[index + 1])
            for index in range(len(vectors) - 1)
        ]
        threshold = _percentile(distances, self._breakpoint_percentile)

        chunks: list[tuple[int, str]] = []
        start = 0
        for index, distance in enumerate(distances):
            # A break after sentence `index` closes the current chunk.
            if distance > threshold:
                chunks.append(self._join(sentences[start : index + 1]))
                start = index + 1
        chunks.append(self._join(sentences[start:]))
        return chunks

    @staticmethod
    def _join(group: list[tuple[str, int]]) -> tuple[int, str]:
        """Join a group of sentences into one chunk tagged with its start page."""
        return group[0][1], " ".join(sentence for sentence, _ in group)
