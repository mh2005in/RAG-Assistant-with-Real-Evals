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


def _chunk_with_pages(pages: list[str], **kwargs: object) -> list[tuple[int, str]]:
    request = FixedSizeChunkingRequest.model_validate({"chunk_size": 5, **kwargs})
    return FixedSizeChunker(request).chunk_with_pages(pages)


def test_chunk_with_pages_tags_each_window_with_its_start_page() -> None:
    # Joined stream "abcdef\nghij" sliced by 5 -> windows start at offsets 0,5,10.
    # Offsets 0 and 5 fall in page 1 (chars 0-6); offset 10 falls in page 2.
    assert _chunk_with_pages(["abcdef", "ghij"]) == [
        (1, "abcde"),
        (1, "f\nghi"),
        (2, "j"),
    ]


def test_chunk_with_pages_reports_page_after_exclusion() -> None:
    # Page 2 is dropped, so the kept stream is page 1 then page 3.
    assert _chunk_with_pages(["p1", "p2", "p3"], chunk_size=100, exclude_pages=[2]) == [
        (1, "p1\np3")
    ]


def test_chunk_with_pages_maps_later_window_to_later_page() -> None:
    # "aaaaa\nbbbbb" (11 chars) by 5 -> offsets 0 (page 1), 5 (page 1, the
    # separator), 10 (page 2).
    assert _chunk_with_pages(["aaaaa", "bbbbb"]) == [
        (1, "aaaaa"),
        (1, "\nbbbb"),
        (2, "b"),
    ]
