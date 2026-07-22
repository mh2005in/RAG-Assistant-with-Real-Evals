"""Request DTO for the answer (augmented generation) stage.

A question to answer from stored documents: the query text, the access role
whose documents may be used as context, and how many chunks to retrieve as that
context.
"""

from pydantic import BaseModel, Field

from dtos.requests.chunking import ChunkingStrategy


class AnswerRequest(BaseModel):
    """Parameters for answering a question from retrieved context."""

    query: str = Field(..., min_length=1, description="The question to answer.")
    access_role: str = Field(
        ...,
        description="Only documents with this access role are used as context.",
    )
    top_k: int = Field(
        default=5,
        gt=0,
        le=100,
        description="How many chunks to retrieve and pass to the model as context.",
    )
    chunking_strategy: ChunkingStrategy | None = Field(
        default=None,
        description=(
            "Only search chunks produced by this chunking strategy. "
            "Omit to search every strategy."
        ),
    )
