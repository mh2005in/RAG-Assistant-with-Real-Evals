"""Request DTO for the evaluation stage.

Evaluation runs against a document already stored by ``/process``, so the request
only needs to identify it: its ``document_id`` and the ``access_role`` allowed to
read it. The role is enforced the same way as retrieval — a caller can only
evaluate documents its role can access.
"""

from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    """Parameters for scoring a stored document's chunking strategies."""

    document_id: int = Field(
        ..., gt=0, description="Id of the stored document to evaluate."
    )
    access_role: str = Field(
        ...,
        description="Only a document with this access role may be evaluated.",
    )
