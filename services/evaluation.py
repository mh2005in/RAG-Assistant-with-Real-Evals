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
"""

import numpy as np
import pandas as pd

from dtos.requests import EvaluateRequest
from dtos.responses import EvaluateResponse, StrategyEvaluation
from services.embedding import Embedder, OllamaEmbedder
from services.storage import PostgresStorage

# A retrieved chunk "hits" the expected answer when its cosine similarity to that
# answer is at least this high. This only feeds the reported ``hit_rate``; the
# ranking itself uses the continuous ``answer_similarity``, so the threshold never
# decides the winner.
_ANSWER_MATCH_THRESHOLD = 0.6


def _best_answer_similarity(
    answer_vector: list[float], chunk_vectors: list[list[float]]
) -> float:
    """Highest cosine similarity between the answer and any retrieved chunk.

    Returns 0.0 when nothing was retrieved. A zero-norm vector contributes 0.0
    similarity rather than a division-by-zero.
    """
    if not chunk_vectors:
        return 0.0
    answer = np.asarray(answer_vector, dtype=float)
    chunks = np.asarray(chunk_vectors, dtype=float)
    answer_norm = float(np.linalg.norm(answer))
    chunk_norms = np.linalg.norm(chunks, axis=1)
    denom = chunk_norms * answer_norm
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = np.where(denom > 0, (chunks @ answer) / denom, 0.0)
    return float(np.max(sims))


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

    def _retrieval_scores(
        self,
        request: EvaluateRequest,
        strategies: list[str],
        storage: PostgresStorage,
    ) -> pd.DataFrame:
        """Retrieve per (strategy, question) and score against the expected answer.

        Returns a tidy frame of one row per (strategy, question) with the best
        answer-match similarity and whether it cleared the hit threshold.
        """
        embedder = self._get_embedder()
        question_vectors = embedder.embed([qa.question for qa in request.qa_pairs])
        answer_vectors = embedder.embed([qa.answer for qa in request.qa_pairs])

        rows: list[dict[str, object]] = []
        for strategy in strategies:
            for index, answer_vector in enumerate(answer_vectors):
                retrieved = storage.search_chunks(
                    question_vectors[index],
                    request.access_role,
                    request.top_k,
                    chunking_strategy=strategy,
                    document_id=request.document_id,
                )
                # Compare the expected answer to what was actually retrieved.
                chunk_vectors = embedder.embed([chunk.text for chunk in retrieved])
                similarity = _best_answer_similarity(answer_vector, chunk_vectors)
                rows.append(
                    {
                        "strategy": strategy,
                        "question": index,
                        "answer_similarity": similarity,
                        "hit": similarity >= _ANSWER_MATCH_THRESHOLD,
                    }
                )
        return pd.DataFrame(
            rows, columns=["strategy", "question", "answer_similarity", "hit"]
        )

    def _rank(self, scores: pd.DataFrame) -> list[StrategyEvaluation]:
        """Aggregate the per-question scores per strategy and mark the winner.

        Strategies are ranked by mean answer similarity (ties broken by name for a
        stable order); the top one is marked ``selected``.
        """
        summary = (
            scores.groupby("strategy")
            .agg(
                questions=("question", "count"),
                answer_similarity=("answer_similarity", "mean"),
                hit_rate=("hit", "mean"),
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
        strategies = sorted(
            storage.read_chunk_texts_by_strategy(
                request.document_id, request.access_role
            )
        )
        if not strategies:
            return EvaluateResponse(document_id=request.document_id)

        scores = self._retrieval_scores(request, strategies, storage)
        evaluations = self._rank(scores)
        winner = next(item.strategy for item in evaluations if item.selected)
        storage.delete_chunks_except(request.document_id, winner)
        return EvaluateResponse(
            document_id=request.document_id,
            chunking_strategy=winner,
            evaluations=evaluations,
        )
