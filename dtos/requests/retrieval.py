"""Request DTO for the retrieval stage.

A retrieval query: the natural-language text to search for, the access role
whose documents may be searched (role-based access is enforced by filtering on
it), and how many chunks to return.
"""

from pydantic import BaseModel, Field

from dtos.requests.chunking import ChunkingStrategy


class RetrievalRequest(BaseModel):
    """Parameters for a similarity search over stored chunks."""

    query: str = Field(
        ..., min_length=1, description="Natural-language text to search for."
    )
    access_role: str = Field(
        ...,
        description="Only chunks of documents with this access role are searched.",
    )
    top_k: int = Field(
        default=5,
        gt=0,
        le=100,
        description="Maximum number of chunks to return, most similar first.",
    )
    chunking_strategy: ChunkingStrategy | None = Field(
        default=None,
        description=(
            "Only search chunks produced by this chunking strategy. "
            "Omit to search every strategy."
        ),
    )
