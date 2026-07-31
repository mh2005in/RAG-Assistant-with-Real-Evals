"""Response DTOs for the evaluation endpoint (evaluation stage).

Evaluation is a *separate* stage from chunking: ``/process`` stores every
strategy's chunks without judging them, and ``/evaluate`` scores them after the
fact against a caller-supplied labelled set (question/expected-answer pairs) and
keeps the best. Each strategy is scored by how well retrieving against it surfaces
the expected answers, so the winner is the one that actually retrieves best for
this document — a labelled retrieval eval, not a structural heuristic.
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
