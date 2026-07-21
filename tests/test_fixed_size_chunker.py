"""Tests for the fixed-size chunker.

Page exclusion is applied upstream (see the FileProcessing tests); the chunker
only groups the words of whatever pages it is handed.
"""

from dtos.requests import FixedSizeChunkingRequest
from services.chunking import FixedSizeChunker


def _chunk(pages: list[str], chunk_size: int = 2) -> list[str]:
    return FixedSizeChunker(FixedSizeChunkingRequest(chunk_size=chunk_size)).chunk(
        pages
    )


def _chunk_with_pages(pages: list[str], chunk_size: int = 2) -> list[tuple[int, str]]:
    request = FixedSizeChunkingRequest(chunk_size=chunk_size)
    return FixedSizeChunker(request).chunk_with_pages(pages)


def test_groups_page_words_into_fixed_windows() -> None:
    # Words across pages: [a, b, c, d, e] -> windows of 2 words each.
    assert _chunk(["a b c", "d e"]) == ["a b", "c d", "e"]


def test_exact_multiple_has_no_trailing_empty_chunk() -> None:
    assert _chunk(["one two"]) == ["one two"]


def test_normalizes_intra_page_whitespace() -> None:
    # Runs of whitespace collapse to single spaces when words are re-joined.
    assert _chunk(["a\t b\n\nc"], chunk_size=100) == ["a b c"]


def test_no_pages_yields_no_chunks() -> None:
    assert _chunk([], chunk_size=100) == []


def test_pages_without_words_yield_no_chunks() -> None:
    assert _chunk(["", "   \n\t "], chunk_size=100) == []


def test_chunk_with_pages_tags_each_window_with_its_start_page() -> None:
    # Words [a, b, c] (page 1) then [d, e] (page 2), windows of 2 words start on
    # the page of their first word: [a,b]->1, [c,d]->1 (c is page 1), [e]->2.
    assert _chunk_with_pages(["a b c", "d e"]) == [
        (1, "a b"),
        (1, "c d"),
        (2, "e"),
    ]


def test_chunk_with_pages_maps_later_window_to_later_page() -> None:
    assert _chunk_with_pages(["a1 a2", "b1 b2"]) == [
        (1, "a1 a2"),
        (2, "b1 b2"),
    ]


def test_blank_page_contributes_nothing_but_keeps_page_numbering() -> None:
    # An excluded page arrives blank; later pages must keep their real numbers.
    assert _chunk_with_pages(["a b", "", "c d"], chunk_size=100) == [(1, "a b c d")]
    assert _chunk_with_pages(["", "c d"], chunk_size=100) == [(2, "c d")]
