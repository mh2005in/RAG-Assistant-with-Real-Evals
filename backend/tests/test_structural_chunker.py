"""Tests for the structural chunker.

Boundaries come from regexes, so nothing here needs an embedder or a model. Most
tests pass ``min_words=0`` to see the raw section boundaries: the default minimum
would merge these deliberately tiny sections back together, which is exercised
separately in :class:`TestSizeBounds`.

Page exclusion is applied upstream (see the FileProcessing tests); the chunker
only splits whatever pages it is handed.
"""

import pytest
from pydantic import ValidationError

from dtos.requests import StructuralChunkingRequest
from services.chunking import StructuralChunker


def _chunk(pages: list[str], **kwargs: object) -> list[str]:
    request = StructuralChunkingRequest.model_validate({"min_words": 0, **kwargs})
    return StructuralChunker(request).chunk(pages)


def _chunk_with_pages(pages: list[str], **kwargs: object) -> list[tuple[int, str]]:
    request = StructuralChunkingRequest.model_validate({"min_words": 0, **kwargs})
    return StructuralChunker(request).chunk_with_pages(pages)


class TestHeadingMarkers:
    """Each built-in marker opens a section, and takes its body with it."""

    def test_splits_at_markdown_headings(self) -> None:
        assert _chunk(["# Intro\nFirst body.\n\n## Detail\nSecond body."]) == [
            "# Intro\nFirst body.",
            "## Detail\nSecond body.",
        ]

    def test_splits_at_numbered_sections(self) -> None:
        assert _chunk(["1. Scope\nWhat we cover.\n2) Limits\nWhat we do not."]) == [
            "1. Scope\nWhat we cover.",
            "2) Limits\nWhat we do not.",
        ]

    def test_splits_at_multi_level_numbers_without_a_terminator(self) -> None:
        assert _chunk(
            ["3.1 Results\nThe numbers.\n3.2 Discussion\nWhat they mean."]
        ) == [
            "3.1 Results\nThe numbers.",
            "3.2 Discussion\nWhat they mean.",
        ]

    def test_a_leading_year_is_not_a_heading(self) -> None:
        # "2010 was busy." opens with a number but has no section terminator, so
        # it stays part of the section it sits in.
        assert _chunk(["# Intro\n2010 was busy.\nAnd so was 2011."]) == [
            "# Intro\n2010 was busy.\nAnd so was 2011."
        ]

    def test_splits_at_labelled_sections_whatever_their_case(self) -> None:
        assert _chunk(["Chapter IV\nThe body.\n\nappendix b\nMore body."]) == [
            "Chapter IV\nThe body.",
            "appendix b\nMore body.",
        ]

    def test_splits_at_roman_and_lettered_items(self) -> None:
        assert _chunk(
            ["IV. Findings\nWhat we found.\nB) Exclusions\nWhat we left."]
        ) == [
            "IV. Findings\nWhat we found.",
            "B) Exclusions\nWhat we left.",
        ]

    def test_splits_at_all_caps_title_lines(self) -> None:
        assert _chunk(["SCOPE OF WORK\nThe body.\n\nPAYMENT TERMS\nMore body."]) == [
            "SCOPE OF WORK\nThe body.",
            "PAYMENT TERMS\nMore body.",
        ]

    def test_an_upper_case_sentence_is_not_a_title(self) -> None:
        # It ends in a period, so it reads as a shouted sentence, not a heading.
        assert _chunk(["# Intro\nTHIS IS SHOUTED TEXT.\nAnd this is not."]) == [
            "# Intro\nTHIS IS SHOUTED TEXT.\nAnd this is not."
        ]

    def test_text_before_the_first_heading_is_its_own_chunk(self) -> None:
        assert _chunk(["A preamble line.\n\n# Intro\nThe body."]) == [
            "A preamble line.",
            "# Intro\nThe body.",
        ]


class TestParagraphFallback:
    """With no marker anywhere, paragraphs are the only structure left."""

    def test_unmarked_text_splits_on_blank_lines(self) -> None:
        assert _chunk(["First paragraph.\n\nSecond paragraph.\n\nThird."]) == [
            "First paragraph.",
            "Second paragraph.",
            "Third.",
        ]

    def test_a_single_marker_switches_off_the_fallback(self) -> None:
        # One heading means the document *is* marked up, so blank lines inside a
        # section no longer split it.
        assert _chunk(["# Intro\nFirst paragraph.\n\nSecond paragraph."]) == [
            "# Intro\nFirst paragraph.\n\nSecond paragraph."
        ]


class TestSizeBounds:
    def test_a_heading_without_a_body_merges_into_the_next_section(self) -> None:
        pages = ["# Part One\n\n## Detail\nThe only body text there is."]

        assert _chunk(pages, min_words=5) == [
            "# Part One\n\n## Detail\nThe only body text there is."
        ]

    def test_a_trailing_short_section_merges_backwards(self) -> None:
        # Nothing follows it, so it joins the section before it instead.
        pages = ["# Intro\none two three four five six\n\n# Note\nshort"]

        assert _chunk(pages, min_words=4) == [
            "# Intro\none two three four five six\n\n# Note\nshort"
        ]

    def test_an_oversized_section_splits_at_paragraphs(self) -> None:
        pages = ["# Intro\n" + "word " * 6 + "\n\n" + "other " * 6]

        chunks = _chunk(pages, max_words=10)

        assert chunks == [("# Intro\n" + "word " * 6).strip(), ("other " * 6).strip()]

    def test_an_oversized_paragraph_splits_at_sentences(self) -> None:
        pages = ["# Intro\nOne two three. Four five six. Seven eight nine."]

        assert _chunk(pages, max_words=7) == [
            "# Intro One two three.",
            "Four five six. Seven eight nine.",
        ]

    def test_an_oversized_sentence_splits_into_word_windows(self) -> None:
        # No boundary is left below a sentence, so it is cut by word count — the
        # heading's own words counting like any other.
        pages = ["# Intro\n" + " ".join(str(number) for number in range(1, 8)) + "."]

        assert _chunk(pages, max_words=3) == ["# Intro 1", "2 3 4", "5 6 7."]

    def test_a_section_within_bounds_is_left_alone(self) -> None:
        pages = ["# Intro\nOne two three. Four five six."]

        assert _chunk(pages, max_words=100) == [
            "# Intro\nOne two three. Four five six."
        ]


class TestPageNumbers:
    def test_tags_each_section_with_its_starting_page(self) -> None:
        assert _chunk_with_pages(["# Intro\nBody one.", "# Detail\nBody two."]) == [
            (1, "# Intro\nBody one."),
            (2, "# Detail\nBody two."),
        ]

    def test_a_section_spanning_pages_reports_where_it_began(self) -> None:
        assert _chunk_with_pages(["# Intro\nBody one.", "Body two."]) == [
            (1, "# Intro\nBody one.\nBody two.")
        ]

    def test_blank_pages_contribute_nothing_without_shifting_numbers(self) -> None:
        # Page 1 was excluded upstream, so it arrives blank; page 2 keeps its number.
        assert _chunk_with_pages(["", "# Intro\nThe body."]) == [
            (2, "# Intro\nThe body.")
        ]

    def test_no_text_yields_no_chunks(self) -> None:
        assert _chunk([]) == []
        assert _chunk(["", "   \n\t "]) == []


class TestRequestOverrides:
    def test_caller_patterns_replace_the_built_in_markers(self) -> None:
        pages = ["# Intro\nBody one.\nClause 2\nBody two."]

        # "# Intro" is no longer a heading; "Clause 2" now is.
        assert _chunk(pages, heading_patterns=[r"^Clause \d+"]) == [
            "# Intro\nBody one.",
            "Clause 2\nBody two.",
        ]

    def test_an_empty_pattern_list_leaves_only_the_paragraph_fallback(self) -> None:
        pages = ["# Intro\nBody one.\n\n# Detail\nBody two."]

        assert _chunk(pages, heading_patterns=[]) == [
            "# Intro\nBody one.",
            "# Detail\nBody two.",
        ]

    def test_defaults_apply_when_no_request_is_given(self) -> None:
        chunker = StructuralChunker()

        assert chunker.chunk(["# Intro\nA short body."]) == ["# Intro\nA short body."]


class TestRequestValidation:
    def test_rejects_a_pattern_that_does_not_compile(self) -> None:
        with pytest.raises(ValidationError, match="invalid regex"):
            StructuralChunkingRequest(heading_patterns=["^(unclosed"])

    def test_rejects_inverted_word_bounds(self) -> None:
        with pytest.raises(ValidationError, match="must not exceed"):
            StructuralChunkingRequest(min_words=100, max_words=10)

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            StructuralChunkingRequest.model_validate({"chunk_size": 100})
