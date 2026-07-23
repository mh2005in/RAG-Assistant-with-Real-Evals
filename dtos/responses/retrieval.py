"""Response DTOs for the retrieval stage.

A retrieval returns the chunks most similar to the query, each tagged with the
document it came from and a similarity score, so callers can use them as RAG
context or cite them.
"""

from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """One chunk returned by a similarity search, with its source and score."""

    document_id: int = Field(..., description="Id of the document the chunk is from.")
    document_name: str = Field(..., description="Name of the source document.")
    chunking_strategy: str = Field(
        ..., description="Chunking strategy that produced this chunk."
    )
    chunk_index: int = Field(
        ..., description="0-based position within the document, for this strategy."
    )
    page_number: int = Field(..., ge=1, description="1-based source page number.")
    text: str = Field(..., description="The chunk's text.")
    score: float = Field(
        ...,
        description="Cosine similarity to the query in [-1, 1]; higher is closer.",
    )


class RetrievalResponse(BaseModel):
    """The ranked chunks matching a retrieval query."""

    query: str = Field(..., description="The query that was searched for.")
    count: int = Field(..., ge=0, description="Number of chunks returned.")
    results: list[RetrievedChunk] = Field(
        default_factory=list, description="Matching chunks, most similar first."
    )
