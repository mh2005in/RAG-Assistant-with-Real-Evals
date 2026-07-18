"""Tests for the fixed-size chunker."""

from dtos.requests import FixedSizeChunkingRequest
from services.chunking import FixedSizeChunker


def _chunk(pages: list[str], **kwargs: object) -> list[str]:
    request = FixedSizeChunkingRequest.model_validate({"chunk_size": 2, **kwargs})
    return FixedSizeChunker(request).chunk(pages)


def test_groups_page_words_into_fixed_windows() -> None:
    # Words across pages: [a, b, c, d, e] -> windows of 2 words each.
    assert _chunk(["a b c", "d e"]) == ["a b", "c d", "e"]


def test_exact_multiple_has_no_trailing_empty_chunk() -> None:
    assert _chunk(["one two"]) == ["one two"]


def test_normalizes_intra_page_whitespace() -> None:
    # Runs of whitespace collapse to single spaces when words are re-joined.
    assert _chunk(["a\t b\n\nc"], chunk_size=100) == ["a b c"]


def test_excludes_single_page_numbers() -> None:
    chunks = _chunk(["p1", "p2", "p3"], chunk_size=100, exclude_pages=[2])
    assert chunks == ["p1 p3"]


def test_excludes_page_ranges() -> None:
    chunks = _chunk(
        ["p1", "p2", "p3", "p4"],
        chunk_size=100,
        exclude_pages=[{"start": 1, "end": 2}],
    )
    assert chunks == ["p3 p4"]


def test_all_pages_excluded_yields_no_chunks() -> None:
    assert _chunk(["p1", "p2"], chunk_size=100, exclude_pages=[1, 2]) == []


def test_no_pages_yields_no_chunks() -> None:
    assert _chunk([], chunk_size=100) == []


def test_pages_without_words_yield_no_chunks() -> None:
    assert _chunk(["", "   \n\t "], chunk_size=100) == []


def _chunk_with_pages(pages: list[str], **kwargs: object) -> list[tuple[int, str]]:
    request = FixedSizeChunkingRequest.model_validate({"chunk_size": 2, **kwargs})
    return FixedSizeChunker(request).chunk_with_pages(pages)


def test_chunk_with_pages_tags_each_window_with_its_start_page() -> None:
    # Words [a, b, c] (page 1) then [d, e] (page 2), windows of 2 words start on
    # the page of their first word: [a,b]->1, [c,d]->1 (c is page 1), [e]->2.
    assert _chunk_with_pages(["a b c", "d e"]) == [
        (1, "a b"),
        (1, "c d"),
        (2, "e"),
    ]


def test_chunk_with_pages_reports_page_after_exclusion() -> None:
    # Page 2 is dropped, so the kept words are page 1 then page 3.
    assert _chunk_with_pages(["p1", "p2", "p3"], chunk_size=100, exclude_pages=[2]) == [
        (1, "p1 p3")
    ]


def test_chunk_with_pages_maps_later_window_to_later_page() -> None:
    # Words [a1, a2] (page 1) then [b1, b2] (page 2), windows of 2 words:
    # [a1,a2]->page 1, [b1,b2]->page 2.
    assert _chunk_with_pages(["a1 a2", "b1 b2"]) == [
        (1, "a1 a2"),
        (2, "b1 b2"),
    ]
