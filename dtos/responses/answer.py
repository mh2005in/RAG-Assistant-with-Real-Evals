"""Response DTO for the answer (augmented generation) stage.

The model's answer plus the chunks that were retrieved and used as context, so
the answer can be traced back to (and cited from) its sources.
"""

from pydantic import BaseModel, Field

from dtos.responses.retrieval import RetrievedChunk


class AnswerResponse(BaseModel):
    """A generated answer and the retrieved chunks it was grounded in."""

    query: str = Field(..., description="The question that was answered.")
    answer: str = Field(..., description="The model's answer, grounded in the sources.")
    sources: list[RetrievedChunk] = Field(
        default_factory=list,
        description="Chunks retrieved as context, most similar first.",
    )
