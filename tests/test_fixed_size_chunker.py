"""Tests for the fixed-size chunker."""

from dtos.requests import FixedSizeChunkingRequest
from services.chunking import FixedSizeChunker


def _chunk(pages: list[str], **kwargs: object) -> list[str]:
    request = FixedSizeChunkingRequest.model_validate({"chunk_size": 5, **kwargs})
    return FixedSizeChunker(request).chunk(pages)


def test_slices_joined_stream_into_fixed_windows() -> None:
    # "abcdef" + "\n" + "ghij" == "abcdef\nghij" (11 chars) -> windows of 5.
    assert _chunk(["abcdef", "ghij"]) == ["abcde", "f\nghi", "j"]


def test_exact_multiple_has_no_trailing_empty_chunk() -> None:
    assert _chunk(["abcde"]) == ["abcde"]


def test_excludes_single_page_numbers() -> None:
    chunks = _chunk(["p1", "p2", "p3"], chunk_size=100, exclude_pages=[2])
    assert chunks == ["p1\np3"]


def test_excludes_page_ranges() -> None:
    chunks = _chunk(
        ["p1", "p2", "p3", "p4"],
        chunk_size=100,
        exclude_pages=[{"start": 1, "end": 2}],
    )
    assert chunks == ["p3\np4"]


def test_all_pages_excluded_yields_no_chunks() -> None:
    assert _chunk(["p1", "p2"], chunk_size=100, exclude_pages=[1, 2]) == []


def test_no_pages_yields_no_chunks() -> None:
    assert _chunk([], chunk_size=100) == []
