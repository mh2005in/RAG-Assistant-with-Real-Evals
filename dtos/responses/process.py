"""Response DTOs for the file-processing endpoint."""

from enum import Enum

from pydantic import BaseModel, Field

from dtos.responses.chunk import Chunk


class DocType(str, Enum):
    """Detected document type of an uploaded file."""

    pdf = "pdf"
    unknown = "unknown"


class ProcessResponse(BaseModel):
    """Result of processing an uploaded file.

    ``chunks`` is populated only when the document could be chunked (currently
    PDFs processed with the fixed-size strategy); each carries its text,
    per-page stats, and an embedding vector. Otherwise it is empty and
    ``chunk_count`` is 0.
    """

    processed: bool
    doc_type: DocType
    chunk_count: int = 0
    chunks: list[Chunk] = Field(default_factory=list)
