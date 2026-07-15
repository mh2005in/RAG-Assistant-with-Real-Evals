"""Response DTOs for the file-processing endpoint."""

from pydantic import BaseModel


class ProcessResponse(BaseModel):
    processed: bool
