"""Request DTOs for chunking strategies.

Each DTO carries only the parameters specific to its strategy. Page exclusion is
common to every strategy and lives in :mod:`dtos.requests.pages`.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ChunkingStrategy(str, Enum):
    """Chunking strategies under evaluation (see README)."""

    fixed = "fixed"
    semantic = "semantic"
    structural = "structural"
    recursive = "recursive"
    llm = "llm"


class FixedSizeChunkingRequest(BaseModel):
    """Parameters for the fixed-size chunking strategy."""

    # Reject unknown keys. ``exclude_pages`` used to live here; without this it
    # would be silently ignored, quietly chunking pages the caller meant to skip.
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(
        ...,
        gt=0,
        description="Number of words per chunk (whitespace-split).",
    )
