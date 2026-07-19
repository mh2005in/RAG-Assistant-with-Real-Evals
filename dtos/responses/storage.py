"""Response DTO for the storage stage.

Returned after a document and its chunks are persisted, so callers get the new
document's primary key (to reference it later) and a count of the chunk rows
written, without the service handing back raw tuples.
"""

from pydantic import BaseModel, Field


class StoredDocument(BaseModel):
    """Result of persisting one document and its chunks."""

    document_id: int = Field(
        ..., description="Primary key of the inserted ``documents`` row."
    )
    chunk_count: int = Field(
        ..., ge=0, description="Number of ``chunks`` rows written for the document."
    )
