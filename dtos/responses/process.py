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
    PDFs processed with the fixed-size strategy); each carries its per-page
    stats plus a clipped preview of its text and embedding (see
    :meth:`Chunk.truncated`) to keep the response small. Otherwise it is empty
    and ``chunk_count`` is 0.

    ``document_id`` is the primary key of the stored ``documents`` row when the
    chunks were persisted, and ``None`` when nothing was stored (e.g. the file
    produced no chunks, or no storage was configured).
    """

    processed: bool
    doc_type: DocType
    chunk_count: int = 0
    chunks: list[Chunk] = Field(default_factory=list)
    document_id: int | None = None
