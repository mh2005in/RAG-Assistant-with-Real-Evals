"""Evaluation service (evaluation stage).

Everything behind the ``/evaluate`` endpoint: read a stored document's chunks
back, score each chunking strategy (cohesion vs separation), keep the best and
delete the losers. Route handlers stay thin and delegate here (see CLAUDE.md).

Scoring is deliberately *separate* from chunking: ``/process`` stores every
strategy without judging it, and this stage decides the winner after the fact. So
a document can be re-evaluated without re-chunking, and chunking never pays the
cost of scoring.

The label-free score itself lives in :func:`~services.chunking.score_chunks` (it
belongs to the chunking stage that defines what a good chunk is); this service
only orchestrates read → score → prune.
"""

from dtos.requests import EvaluateRequest
from dtos.responses import EvaluateResponse, StrategyEvaluation
from services.chunking import score_chunks
from services.embedding import Embedder, OllamaEmbedder
from services.storage import PostgresStorage


class Evaluation:
    """Score a stored document's chunking strategies and keep the best.

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

    def _score(
        self, chunks_by_strategy: dict[str, list[str]]
    ) -> list[StrategyEvaluation]:
        """Score each strategy's chunk texts, best first, marking the winner.

        Scoring is label-free (cohesion vs separation, see
        :func:`~services.chunking.score_chunks`), so it works on whatever document
        was stored. The highest score is marked ``selected``.
        """
        embedder = self._get_embedder()
        scored: list[StrategyEvaluation] = []
        for strategy, texts in chunks_by_strategy.items():
            cohesion, separation, score = score_chunks(texts, embedder)
            word_counts = [len(text.split()) for text in texts]
            scored.append(
                StrategyEvaluation(
                    strategy=strategy,
                    chunk_count=len(texts),
                    mean_chunk_words=(
                        round(sum(word_counts) / len(word_counts), 2)
                        if word_counts
                        else 0.0
                    ),
                    cohesion=round(cohesion, 4),
                    separation=round(separation, 4),
                    score=round(score, 4),
                    selected=False,
                )
            )

        scored.sort(key=lambda evaluation: evaluation.score, reverse=True)
        if scored:
            scored[0] = scored[0].model_copy(update={"selected": True})
        return scored

    def evaluate(
        self, request: EvaluateRequest, storage: PostgresStorage
    ) -> EvaluateResponse:
        """Score the stored document's strategies, keep the winner, drop the rest.

        Reads back the chunks ``/process`` stored (filtered to the request's
        access role), scores every strategy that is still present, and deletes all
        but the winner's chunks — so the document ends up holding exactly one
        strategy. If the document has no readable chunks, nothing is scored or
        deleted and the winner is ``None``.
        """
        chunks_by_strategy = storage.read_chunk_texts_by_strategy(
            request.document_id, request.access_role
        )
        evaluations = self._score(chunks_by_strategy)
        if not evaluations:
            return EvaluateResponse(document_id=request.document_id)

        winner = next(item.strategy for item in evaluations if item.selected)
        storage.delete_chunks_except(request.document_id, winner)
        return EvaluateResponse(
            document_id=request.document_id,
            chunking_strategy=winner,
            evaluations=evaluations,
        )
