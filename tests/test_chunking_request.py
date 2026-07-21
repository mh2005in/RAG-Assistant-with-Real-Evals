"""Tests for the fixed-size chunking request DTO."""

import pytest
from pydantic import ValidationError

from dtos.requests import FixedSizeChunkingRequest


def test_accepts_a_positive_chunk_size() -> None:
    assert FixedSizeChunkingRequest(chunk_size=200).chunk_size == 200


def test_rejects_non_positive_chunk_size() -> None:
    with pytest.raises(ValidationError):
        FixedSizeChunkingRequest(chunk_size=0)


def test_rejects_unknown_fields() -> None:
    # exclude_pages used to live here. Silently ignoring it would chunk pages the
    # caller meant to skip, so unknown keys must fail loudly.
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FixedSizeChunkingRequest.model_validate(
            {"chunk_size": 100, "exclude_pages": [1]}
        )
