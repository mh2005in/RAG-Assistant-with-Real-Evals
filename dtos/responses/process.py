"""Response DTOs for the file-processing endpoint."""

from enum import Enum

from pydantic import BaseModel, Field

from dtos.responses.chunk import Chunk


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
    only the winner's chunks are kept in the database. ``evaluations`` reports how
    all of them did, and ``chunking_strategy`` names the one that remains.

    ``chunks`` is populated only when the document could be chunked (currently
    PDFs); each carries its per-page stats plus a clipped preview of its text and
    embedding (see :meth:`Chunk.truncated`) to keep the response small. Otherwise
    it is empty and ``chunk_count`` is 0.
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
    chunk_count: int = 0
    chunks: list[Chunk] = Field(default_factory=list)
