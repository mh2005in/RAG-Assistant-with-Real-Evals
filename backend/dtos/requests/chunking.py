"""Request DTOs for chunking strategies.

Each DTO carries only the parameters specific to its strategy. Page exclusion is
common to every strategy and lives in :mod:`dtos.requests.pages`.
"""

import re
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Bounds on a structural section, in words. Sections below the minimum (a bare
# heading, a one-line preamble) merge into the next; ones above the maximum are
# split down, keeping every chunk comfortably inside the embedding model's window.
_DEFAULT_MIN_WORDS = 25
_DEFAULT_MAX_WORDS = 400


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


class StructuralChunkingRequest(BaseModel):
    """Parameters for the structural chunking strategy.

    Every field is optional: the strategy has working defaults, so a caller who
    does not care about structure never has to describe it.
    """

    model_config = ConfigDict(extra="forbid")

    heading_patterns: list[str] | None = Field(
        default=None,
        description=(
            "Regexes marking the start of a new section, matched against each "
            "stripped line. Omit to use the strategy's built-in markers "
            "(markdown headings, numbered/labelled sections, ALL-CAPS titles)."
        ),
    )
    min_words: int = Field(
        default=_DEFAULT_MIN_WORDS,
        ge=0,
        description="Sections shorter than this merge into the next one.",
    )
    max_words: int = Field(
        default=_DEFAULT_MAX_WORDS,
        gt=0,
        description="Sections longer than this are split at the next-finest boundary.",
    )

    @field_validator("heading_patterns")
    @classmethod
    def _patterns_must_compile(cls, patterns: list[str] | None) -> list[str] | None:
        """Reject an unusable regex here, so a bad pattern is a 422 and not a 500."""
        for pattern in patterns or []:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
        return patterns

    @model_validator(mode="after")
    def _bounds_must_be_ordered(self) -> Self:
        """An inverted pair would merge and split the same section forever."""
        if self.min_words > self.max_words:
            raise ValueError(
                f"min_words ({self.min_words}) must not exceed "
                f"max_words ({self.max_words})"
            )
        return self
