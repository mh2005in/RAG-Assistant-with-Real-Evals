"""Rank-aware retrieval metrics (retrieval stage).

Answer similarity says *how close* the best retrieved chunk was to the expected
answer; it says nothing about **where in the ranking** the useful chunks landed.
A strategy that surfaces the right chunk at position 1 and one that buries it at
position 5 can score the same. These are the standard metrics that do look at
rank:

* **recall@k** — of all the chunks that *could* have answered the question, what
  fraction made it into the top ``k``. Measures coverage, ignores order.
* **MRR** (reciprocal rank) — ``1 / rank`` of the first relevant chunk, so
  position 1 scores 1.0, position 2 scores 0.5, and nothing relevant scores 0.0.
  Measures how fast a reader reaches something useful.
* **nDCG@k** — discounted cumulative gain over the whole ranked list, normalised
  by the best ordering that list could have had. Rewards putting *every* relevant
  chunk early, not just the first one.

Relevance is **binary** and is decided by the caller, which keeps this module
pure arithmetic: no embedder, no storage, no threshold policy. The evaluation
service labels a chunk relevant when its similarity to the expected answer clears
the same threshold that already drives ``hit_rate``, so the rank-aware numbers and
the hit rate agree on what "relevant" means.

``relevant_total`` is the count of relevant chunks in the **full candidate pool**
(every chunk the retriever could have returned), not just among those retrieved —
otherwise recall@k has no honest denominator and would read 1.0 whenever anything
relevant surfaced. When a question has no relevant chunk anywhere in the pool,
recall and nDCG are **undefined** rather than zero: the retriever cannot be
faulted for missing what does not exist. Both return ``None`` so the caller can
skip that question instead of averaging in a penalty it did not earn. Reciprocal
rank stays defined at 0.0 — no relevant chunk was reached, whatever the reason.
"""

import math
from collections.abc import Sequence


def _dcg(gains: Sequence[float]) -> float:
    """Discounted cumulative gain over ``gains`` in rank order.

    Rank is 1-based, so the discount is ``log2(rank + 1)``: the first position is
    undiscounted and each later one counts for less.
    """
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))


def recall_at_k(relevance: Sequence[bool], relevant_total: int) -> float | None:
    """Fraction of the pool's relevant chunks that the ranked list retrieved.

    ``relevance`` labels the retrieved chunks in rank order; ``relevant_total``
    counts the relevant chunks in the whole pool. Returns ``None`` when the pool
    holds none, which makes the metric undefined rather than zero.

    Capped by the list length: with more relevant chunks than retrieved slots a
    perfect retriever still scores below 1.0, which is the honest reading of
    recall *at k*.
    """
    if relevant_total <= 0:
        return None
    return sum(relevance) / relevant_total


def reciprocal_rank(relevance: Sequence[bool]) -> float:
    """``1 / rank`` of the first relevant chunk, or 0.0 if none is relevant.

    Averaged over questions by the caller, this is MRR. Always defined — a
    question with no relevant chunk in the pool simply never reaches one.
    """
    for rank, is_relevant in enumerate(relevance, start=1):
        if is_relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevance: Sequence[bool], relevant_total: int) -> float | None:
    """Normalised discounted cumulative gain of the ranked list.

    Binary gains: a relevant chunk contributes 1, discounted by its rank. The
    ideal ordering puts as many relevant chunks as the list can hold —
    ``min(relevant_total, len(relevance))`` of them — at the top, so a list that
    cannot fit every relevant chunk is not punished for the ones it had no room
    for. Returns ``None`` when the pool holds no relevant chunk, matching
    :func:`recall_at_k`.
    """
    if relevant_total <= 0:
        return None
    ideal_hits = min(relevant_total, len(relevance))
    ideal = _dcg([1.0] * ideal_hits)
    if ideal == 0.0:
        # Nothing could have been retrieved (an empty ranked list); no ordering
        # would have scored better, so there is nothing to normalise against.
        return 0.0
    return _dcg([1.0 if is_relevant else 0.0 for is_relevant in relevance]) / ideal
