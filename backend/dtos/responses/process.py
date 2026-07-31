"""Response DTOs for the file-processing endpoint."""

from enum import Enum

from pydantic import BaseModel, Field


class DocType(str, Enum):
    """Detected document type of an uploaded file."""

    pdf = "pdf"
    unknown = "unknown"


class StoredStrategy(BaseModel):
    """One chunking strategy's chunks that were stored for a document.

    ``/process`` stores every strategy side by side without judging them; each
    entry here reports how many chunks a strategy contributed. Which one is
    "best" is decided later by ``/evaluate``, not at processing time.
    """

    strategy: str = Field(..., description="Chunking strategy that was stored.")
    chunk_count: int = Field(
        ..., ge=0, description="Chunks this strategy contributed to the document."
    )


class ProcessResponse(BaseModel):
    """Result of processing an uploaded file.

    The document is chunked with *every* implemented strategy and all of their
    chunks are stored against one ``documents`` row — no strategy is scored or
    dropped here. Scoring is a separate stage: call ``/evaluate`` to compare the
    stored strategies and keep the best. The response reports which strategies
    were stored (``strategies``) and their chunk counts, not the chunks
    themselves; the stored chunks are read back via ``/retrieve``.
    """

    processed: bool
    doc_type: DocType
    document_id: int | None = Field(
        default=None,
        description="Primary key of the stored document, or null if nothing was stored.",
    )
    strategies: list[StoredStrategy] = Field(
        default_factory=list,
        description="Every strategy stored for the document, with its chunk count.",
    )
