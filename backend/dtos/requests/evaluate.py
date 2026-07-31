"""Request DTOs for the evaluation stage.

Evaluation runs against a document already stored by ``/process``. The caller
supplies a small labelled set — question/expected-answer pairs — and each
chunking strategy is scored by how well retrieving against that strategy surfaces
the expected answers. The request identifies the document (``document_id``), the
``access_role`` allowed to read it (enforced the same way retrieval is), and the
``qa_pairs`` to evaluate against.
"""

from pydantic import BaseModel, Field


class QAPair(BaseModel):
    """One labelled example: a question and the answer it should retrieve."""

    question: str = Field(
        ..., min_length=1, description="Question to retrieve context for."
    )
    answer: str = Field(
        ...,
        min_length=1,
        description="Expected answer the retrieved chunks should support.",
    )


class EvaluateRequest(BaseModel):
    """Parameters for scoring a stored document's chunking strategies.

    Each strategy is evaluated by retrieving against it for every question and
    comparing the retrieved chunks to the expected answer; the strategy whose
    retrievals best match the answers wins.
    """

    document_id: int = Field(
        ..., gt=0, description="Id of the stored document to evaluate."
    )
    access_role: str = Field(
        ...,
        description="Only a document with this access role may be evaluated.",
    )
    qa_pairs: list[QAPair] = Field(
        ...,
        min_length=1,
        description="Labelled question/expected-answer pairs to score against.",
    )
    top_k: int = Field(
        default=5,
        gt=0,
        le=100,
        description="Chunks to retrieve per question when scoring a strategy.",
    )
