"""Response DTOs for the file-processing endpoint."""

from enum import Enum

from pydantic import BaseModel, Field


class DocType(str, Enum):
    """Detected document type of an uploaded file."""

    pdf = "pdf"
    unknown = "unknown"


class StrategyEvaluation(BaseModel):
    """How one chunking strategy scored on the uploaded document.

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


class ProcessResponse(BaseModel):
    """Result of processing an uploaded file.

    The document is chunked with every implemented strategy, each is scored, and
    only the winner's chunks are kept in the database. The response carries the
    *evaluation*, not the chunks themselves: ``evaluations`` reports how every
    strategy did (including its chunk count and mean size) and ``chunking_strategy``
    names the one that remains. The stored chunks are read back via ``/retrieve``.
    """

    processed: bool
    doc_type: DocType
    document_id: int | None = Field(
        default=None,
        description="Primary key of the stored document, or null if nothing was stored.",
    )
    chunking_strategy: str | None = Field(
        default=None,
        description="The winning strategy, whose chunks remain in the database.",
    )
    evaluations: list[StrategyEvaluation] = Field(
        default_factory=list,
        description="Every strategy's score, best first.",
    )
