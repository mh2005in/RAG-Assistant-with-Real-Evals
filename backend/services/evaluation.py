"""Evaluation service (evaluation stage).

Everything behind the ``/evaluate`` endpoint: score a stored document's chunking
strategies against a caller-supplied labelled set (question/expected-answer
pairs), keep the best and delete the losers. Route handlers stay thin and
delegate here (see CLAUDE.md).

Scoring is deliberately *separate* from chunking: ``/process`` stores every
strategy without judging it, and this stage decides the winner after the fact. So
a document can be re-evaluated (e.g. with a different question set) without
re-chunking.

The metric is a labelled retrieval eval. For each question the document's chunks
are retrieved *per strategy* (via the same pgvector search retrieval uses), and
each retrieval is compared to the expected answer by cosine similarity. The
per-question scores are aggregated per strategy with pandas; the strategy whose
retrievals best match the expected answers wins.

Alongside that, every retrieval is also scored with the rank-aware metrics in
:mod:`services.rank_metrics` — recall@k, MRR and nDCG@k — which ask *where in the
ranking* the useful chunks landed rather than only how close the best one came.
They are reported, never used for selection: the winner is still the strategy with
the highest ``answer_similarity``, so adding them left the ranking untouched.
"""

import math

import numpy as np
import pandas as pd

from dtos.requests import EvaluateRequest
from dtos.responses import EvaluateResponse, StrategyEvaluation
from services.embedding import Embedder, OllamaEmbedder
from services.rank_metrics import ndcg_at_k, recall_at_k, reciprocal_rank
from services.storage import PostgresStorage

# A retrieved chunk "hits" the expected answer when its cosine similarity to that
# answer is at least this high. It feeds the reported ``hit_rate`` and decides
# which chunks count as *relevant* for the rank-aware metrics, so the two agree on
# what relevance means. The ranking itself uses the continuous
# ``answer_similarity``, so the threshold never decides the winner.
ANSWER_MATCH_THRESHOLD = 0.6


def _cosine_similarities(
    answer_vector: list[float], chunk_vectors: list[list[float]]
) -> np.ndarray:
    """Cosine similarity between the answer and each chunk vector, in order.

    Returns an empty array when there are no chunks. A zero-norm vector on either
    side contributes 0.0 similarity rather than a division-by-zero.
    """
    if not chunk_vectors:
        return np.empty(0, dtype=float)
    answer = np.asarray(answer_vector, dtype=float)
    chunks = np.asarray(chunk_vectors, dtype=float)
    answer_norm = float(np.linalg.norm(answer))
    chunk_norms = np.linalg.norm(chunks, axis=1)
    denom = chunk_norms * answer_norm
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(np.where(denom > 0, (chunks @ answer) / denom, 0.0))


def _mean_or_none(value: float) -> float | None:
    """Round a pandas mean, turning an all-skipped column back into ``None``.

    recall@k and nDCG@k are undefined for a question whose expected answer matches
    nothing in the document, and those questions are held as NaN so the mean skips
    them. A NaN mean means *every* question was skipped, which is not a score of
    zero — it is the absence of one.
    """
    return None if math.isnan(value) else round(value, 4)


class Evaluation:
    """Score a stored document's chunking strategies against labelled Q&A.

    The embedder loads its model lazily on first use, so constructing the service
    (and importing the app) stays cheap until a document is actually scored. Pass
    an ``embedder`` to override the model/device or to inject a fake in tests.
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = OllamaEmbedder.from_env()
        return self._embedder

    def _embed_distinct(
        self, texts: list[str], vectors: dict[str, list[float]]
    ) -> dict[str, list[float]]:
        """Fill ``vectors`` with an embedding for every text it does not hold yet.

        Keying by text rather than by position lets one set of vectors serve both a
        strategy's candidate pool and the chunks retrieved out of it, so a chunk is
        embedded once per strategy instead of once per question that retrieves it.
        Identical text embeds to an identical vector, so the reuse is exact rather
        than an approximation.
        """
        missing = [text for text in dict.fromkeys(texts) if text not in vectors]
        if missing:
            vectors.update(zip(missing, self._get_embedder().embed(missing)))
        return vectors

    def _retrieval_scores(
        self,
        request: EvaluateRequest,
        chunks_by_strategy: dict[str, list[str]],
        storage: PostgresStorage,
    ) -> pd.DataFrame:
        """Retrieve per (strategy, question) and score against the expected answer.

        Returns a tidy frame of one row per (strategy, question) with the best
        answer-match similarity, whether it cleared the hit threshold, and the
        rank-aware metrics over the retrieved ranking.

        ``chunks_by_strategy`` carries each strategy's whole candidate pool, which
        is what gives recall@k an honest denominator: relevance is counted over
        every chunk the retriever *could* have returned, not only the ones it did.
        """
        embedder = self._get_embedder()
        question_vectors = embedder.embed([qa.question for qa in request.qa_pairs])
        answer_vectors = embedder.embed([qa.answer for qa in request.qa_pairs])

        rows: list[dict[str, object]] = []
        for strategy in sorted(chunks_by_strategy):
            pool_texts = chunks_by_strategy[strategy]
            vectors_by_text = self._embed_distinct(pool_texts, {})
            pool_vectors = [vectors_by_text[text] for text in pool_texts]

            for index, answer_vector in enumerate(answer_vectors):
                retrieved = storage.search_chunks(
                    question_vectors[index],
                    request.access_role,
                    request.top_k,
                    chunking_strategy=strategy,
                    document_id=request.document_id,
                )
                # Compare the expected answer to what was actually retrieved,
                # reusing the pool's vectors for the chunks that came back.
                texts = [chunk.text for chunk in retrieved]
                self._embed_distinct(texts, vectors_by_text)
                sims = _cosine_similarities(
                    answer_vector, [vectors_by_text[text] for text in texts]
                )
                similarity = float(np.max(sims)) if sims.size else 0.0

                # Which retrieved chunks are relevant, in rank order, and how many
                # relevant ones the pool held at all.
                relevance = [bool(value) for value in sims >= ANSWER_MATCH_THRESHOLD]
                pool_sims = _cosine_similarities(answer_vector, pool_vectors)
                relevant_total = int(
                    np.count_nonzero(pool_sims >= ANSWER_MATCH_THRESHOLD)
                )

                rows.append(
                    {
                        "strategy": strategy,
                        "question": index,
                        "answer_similarity": similarity,
                        "hit": similarity >= ANSWER_MATCH_THRESHOLD,
                        # None for a question nothing in the document answers;
                        # pandas holds it as NaN and the mean skips it rather than
                        # scoring the retriever zero for an impossible question.
                        "recall_at_k": recall_at_k(relevance, relevant_total),
                        "reciprocal_rank": reciprocal_rank(relevance),
                        "ndcg_at_k": ndcg_at_k(relevance, relevant_total),
                    }
                )
        return pd.DataFrame(
            rows,
            columns=[
                "strategy",
                "question",
                "answer_similarity",
                "hit",
                "recall_at_k",
                "reciprocal_rank",
                "ndcg_at_k",
            ],
        )

    def _rank(self, scores: pd.DataFrame) -> list[StrategyEvaluation]:
        """Aggregate the per-question scores per strategy and mark the winner.

        Strategies are ranked by mean answer similarity (ties broken by name for a
        stable order); the top one is marked ``selected``. The rank-aware means are
        reported alongside and take no part in the ordering.
        """
        summary = (
            scores.groupby("strategy")
            .agg(
                questions=("question", "count"),
                answer_similarity=("answer_similarity", "mean"),
                hit_rate=("hit", "mean"),
                recall_at_k=("recall_at_k", "mean"),
                mrr=("reciprocal_rank", "mean"),
                ndcg_at_k=("ndcg_at_k", "mean"),
            )
            .reset_index()
            .sort_values(["answer_similarity", "strategy"], ascending=[False, True])
        )

        evaluations = [
            StrategyEvaluation(
                strategy=str(record["strategy"]),
                questions=int(record["questions"]),
                answer_similarity=round(float(record["answer_similarity"]), 4),
                hit_rate=round(float(record["hit_rate"]), 4),
                recall_at_k=_mean_or_none(float(record["recall_at_k"])),
                mrr=round(float(record["mrr"]), 4),
                ndcg_at_k=_mean_or_none(float(record["ndcg_at_k"])),
                selected=False,
            )
            for record in summary.to_dict("records")
        ]
        if evaluations:
            evaluations[0] = evaluations[0].model_copy(update={"selected": True})
        return evaluations

    def evaluate(
        self, request: EvaluateRequest, storage: PostgresStorage
    ) -> EvaluateResponse:
        """Score the document's strategies on the Q&A set, keep the best, drop rest.

        Reads which strategies ``/process`` stored (filtered to the request's
        access role), retrieves against each for every question, ranks them by how
        well their retrievals match the expected answers, and deletes all but the
        winner's chunks — so the document ends up holding exactly one strategy. If
        the document has no readable chunks, nothing is scored or deleted and the
        winner is ``None``.
        """
        chunks_by_strategy = storage.read_chunk_texts_by_strategy(
            request.document_id, request.access_role
        )
        if not chunks_by_strategy:
            return EvaluateResponse(document_id=request.document_id)

        scores = self._retrieval_scores(request, chunks_by_strategy, storage)
        evaluations = self._rank(scores)
        winner = next(item.strategy for item in evaluations if item.selected)
        storage.delete_chunks_except(request.document_id, winner)
        return EvaluateResponse(
            document_id=request.document_id,
            chunking_strategy=winner,
            evaluations=evaluations,
        )
