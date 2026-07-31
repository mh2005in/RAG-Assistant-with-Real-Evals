"""Label-free chunking quality: cohesion vs separation (chunking stage).

Scores a set of chunks without needing labelled data, so ``/process`` can compare
every strategy on the document it was just given and keep the best one.

The score is silhouette-like, computed over sentence embeddings:

* **cohesion** — how similar a chunk's own sentences are to each other, averaged
  over chunks. High means each chunk is about one thing.
* **separation** — how similar *neighbouring* chunks are, averaged over adjacent
  pairs. Low means the boundaries fall where the content actually changes.
* **score = cohesion - separation** — higher is better.

The two terms balance each other, which is what makes the score usable as a
selection rule: splitting too finely leaves neighbours nearly identical (high
separation), while lumping everything together mixes topics inside a chunk (low
cohesion). Both drag the score down.

This measures chunk *structure*, not downstream answer quality; a retrieval eval
against labelled queries is still the stronger signal when one exists.
"""

import math

from services.chunking.sentences import split_sentences
from services.embedding import Embedder

# A chunk with a single sentence has no internal pairs to compare; it is
# trivially cohesive. Over-splitting is punished by the separation term instead.
_SINGLE_SENTENCE_COHESION = 1.0


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity between two vectors (0.0 if either has no direction)."""
    dot = sum(x * y for x, y in zip(left, right))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(y * y for y in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _centroid(vectors: list[list[float]]) -> list[float]:
    """Mean vector of ``vectors`` (which must be non-empty)."""
    count = len(vectors)
    return [sum(values) / count for values in zip(*vectors)]


def _mean_pairwise_similarity(vectors: list[list[float]]) -> float:
    """Average cosine similarity over every distinct pair in ``vectors``."""
    if len(vectors) < 2:
        return _SINGLE_SENTENCE_COHESION
    sims = [
        _cosine_similarity(vectors[i], vectors[j])
        for i in range(len(vectors))
        for j in range(i + 1, len(vectors))
    ]
    return sum(sims) / len(sims)


def score_chunks(chunks: list[str], embedder: Embedder) -> tuple[float, float, float]:
    """Return ``(cohesion, separation, score)`` for ``chunks``.

    Every sentence across every chunk is embedded in one batch, then grouped back
    per chunk, so the strategies being compared are scored on identical footing.
    An empty set of chunks scores zero on all three.
    """
    per_chunk = [split_sentences(chunk) for chunk in chunks]
    # A chunk whose text has no sentence-ending punctuation still counts as one
    # sentence, otherwise it would silently vanish from the score.
    per_chunk = [
        sentences or ([chunk] if chunk.strip() else [])
        for sentences, chunk in zip(per_chunk, chunks)
    ]
    per_chunk = [sentences for sentences in per_chunk if sentences]
    if not per_chunk:
        return 0.0, 0.0, 0.0

    flat = [sentence for sentences in per_chunk for sentence in sentences]
    vectors = embedder.embed(flat)

    grouped: list[list[list[float]]] = []
    offset = 0
    for sentences in per_chunk:
        grouped.append(vectors[offset : offset + len(sentences)])
        offset += len(sentences)

    cohesion = sum(_mean_pairwise_similarity(group) for group in grouped) / len(grouped)

    if len(grouped) < 2:
        # A single chunk has no neighbour, so separation is vacuously 0 — which
        # would hand "don't chunk at all" the best possible score. Like a
        # silhouette with one cluster the score is undefined, so report 0.0:
        # no structure was found. A genuine split beats it whenever its chunks
        # are more self-similar than they are similar to their neighbours, and
        # loses to it when the split is worse than not splitting (negative).
        return cohesion, 0.0, 0.0

    centroids = [_centroid(group) for group in grouped]
    adjacent = [
        _cosine_similarity(centroids[i], centroids[i + 1])
        for i in range(len(centroids) - 1)
    ]
    separation = sum(adjacent) / len(adjacent)

    return cohesion, separation, cohesion - separation
