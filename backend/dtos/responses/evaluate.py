"""Response DTOs for the evaluation endpoint (evaluation stage).

Evaluation is a *separate* stage from chunking: ``/process`` stores every
strategy's chunks without judging them, and ``/evaluate`` scores them after the
fact against a caller-supplied labelled set (question/expected-answer pairs) and
keeps the best. Each strategy is scored by how well retrieving against it surfaces
the expected answers, so the winner is the one that actually retrieves best for
this document — a labelled retrieval eval, not a structural heuristic.

Two kinds of number are reported. ``answer_similarity`` and ``hit_rate`` ask how
*close* the retrieved chunks came to the expected answer; ``recall_at_k``, ``mrr``
and ``ndcg_at_k`` ask where in the ranking the useful chunks landed (see
:mod:`services.rank_metrics`). Only ``answer_similarity`` ranks the strategies —
the rank-aware metrics are reported for insight, not selection.
"""

from pydantic import BaseModel, Field


class StrategyEvaluation(BaseModel):
    """How one chunking strategy scored on the labelled question set.

    For every question, the strategy's chunks are retrieved and compared to the
    expected answer; ``answer_similarity`` is the mean over questions of the best
    match between the retrieved chunks and the expected answer. The strategy with
    the highest ``answer_similarity`` is kept and the rest are deleted (see
    ``selected``).
    """

    strategy: str = Field(..., description="Chunking strategy that was evaluated.")
    questions: int = Field(
        ..., ge=0, description="Number of question/answer pairs scored."
    )
    answer_similarity: float = Field(
        ...,
        description=(
            "Mean over questions of the best cosine similarity between the "
            "retrieved chunks and the expected answer; higher is better. Ranks the "
            "strategies."
        ),
    )
    hit_rate: float = Field(
        ...,
        ge=0,
        le=1,
        description=(
            "Fraction of questions whose expected answer was matched above the "
            "similarity threshold by at least one retrieved chunk."
        ),
    )
    recall_at_k: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Mean over questions of the fraction of the strategy's relevant chunks "
            "that reached the top-k retrieval; higher is better. Questions whose "
            "expected answer matches no chunk at all are skipped, and null means "
            "every question was skipped — the answers are not in this document."
        ),
    )
    mrr: float = Field(
        ...,
        ge=0,
        le=1,
        description=(
            "Mean reciprocal rank: 1/position of the first relevant chunk, averaged "
            "over questions. 1.0 means the first hit was always ranked first."
        ),
    )
    ndcg_at_k: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Mean normalised discounted cumulative gain over the top-k retrieval; "
            "rewards ranking every relevant chunk early, not just the first. Skips "
            "the same unanswerable questions as recall_at_k, and is null when every "
            "question was skipped."
        ),
    )
    selected: bool = Field(
        ..., description="Whether this strategy was kept (the others are deleted)."
    )


class EvaluateResponse(BaseModel):
    """Result of evaluating a stored document's chunking strategies.

    Every strategy still held for the document is scored against the labelled
    questions, the winner's chunks are kept and the losers' deleted, so after a
    successful evaluation the document holds exactly one strategy's chunks.
    ``evaluations`` reports how each strategy did (best first) and
    ``chunking_strategy`` names the one that remains.
    """

    document_id: int = Field(
        ..., description="Primary key of the document that was evaluated."
    )
    chunking_strategy: str | None = Field(
        default=None,
        description="The winning strategy, whose chunks remain in the database.",
    )
    evaluations: list[StrategyEvaluation] = Field(
        default_factory=list,
        description="Every strategy's score, best first.",
    )
