"""Response DTOs for the evaluation endpoint (evaluation stage).

Evaluation is a *separate* stage from chunking: ``/process`` stores every
strategy's chunks without judging them, and ``/evaluate`` scores a stored
document's strategies after the fact and keeps the best. Keeping the two apart
means chunking never pays the cost of scoring, and the same document can be
re-evaluated (e.g. with a different metric) without re-chunking.
"""

from pydantic import BaseModel, Field


class StrategyEvaluation(BaseModel):
    """How one chunking strategy scored on a stored document.

    ``score`` is ``cohesion - separation``; higher is better. The strategy with
    the highest score is kept and the rest are deleted (see ``selected``).
    """

    strategy: str = Field(..., description="Chunking strategy that was evaluated.")
    chunk_count: int = Field(..., ge=0, description="Chunks the strategy produced.")
    mean_chunk_words: float = Field(
        ..., ge=0, description="Average chunk length in words."
    )
    cohesion: float = Field(
        ...,
        description="Mean similarity between sentences inside a chunk; higher is better.",
    )
    separation: float = Field(
        ...,
        description="Mean similarity between neighbouring chunks; lower is better.",
    )
    score: float = Field(
        ..., description="cohesion - separation; the strategy with the highest wins."
    )
    selected: bool = Field(
        ..., description="Whether this strategy was kept (the others are deleted)."
    )


class EvaluateResponse(BaseModel):
    """Result of evaluating a stored document's chunking strategies.

    Every strategy still held for the document is scored (cohesion vs
    separation), the winner's chunks are kept and the losers' deleted, so after a
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
