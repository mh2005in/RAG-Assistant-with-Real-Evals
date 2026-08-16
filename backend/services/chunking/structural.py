"""Structural chunking strategy (chunking stage).

Splits a document where its *structure* changes. A line matching one of the
heading patterns — a markdown heading, a numbered section, a "Chapter 3" /
"Appendix B" label, a roman or lettered item, an ALL-CAPS title line — opens a new
chunk, so each chunk is one section with its own heading attached.

Boundaries come from regexes over line starts, which makes this cheap and
deterministic: unlike the semantic strategy it needs no embedding pass, and unlike
fixed-size it never cuts mid-section. Its blind spot is the mirror image of that:
it only sees structure a document actually marks up. A document with no markers at
all falls back to blank-line paragraph boundaries rather than becoming one
document-sized chunk.

Section sizes are bounded on both sides, because raw sections are not evenly
useful: one under ``min_words`` (a bare heading, a one-line preamble) merges into
the next, and one over ``max_words`` is split at the coarsest boundary that fits —
paragraph, then sentence, then a hard word window.

Page exclusion is applied upstream, so an excluded page arrives blank and
contributes no lines.
"""

import re

from dtos.requests import StructuralChunkingRequest
from services.chunking.sentences import split_sentences

# A line of text paired with the 1-based page it came from.
_Line = tuple[str, int]
# Consecutive lines forming one section (blank separator lines included).
_Section = list[_Line]

# Line-start markers that open a new section, matched against the stripped line.
# Case-sensitivity is per pattern rather than global: the ALL-CAPS marker depends
# on case, so patterns that should ignore it carry their own inline ``(?i)``.
_DEFAULT_HEADING_PATTERNS: tuple[str, ...] = (
    # Markdown heading: "## Background"
    r"^#{1,6}\s+\S",
    # Numbered section: "1. Introduction", "2) Method". The terminator is required
    # at a single level, otherwise a line opening with a year ("2010 was busy")
    # would read as a heading.
    r"^\d+[.)]\s+\S",
    # Multi-level numbered section, where the terminator is often dropped:
    # "3.1 Results", "4.2.1) Details"
    r"^\d+(?:\.\d+)+[.)]?\s+\S",
    # Labelled section: "Chapter IV", "Appendix B", "Section 7"
    r"(?i)^(?:chapter|section|part|appendix|annex|article|schedule|exhibit)"
    r"\s+(?:\d+|[ivxlcdm]+|[a-z])\b",
    # Roman item: "IV. Findings"
    r"^[IVXLCDM]{1,7}[.)]\s+\S",
    # Lettered item: "B) Exclusions"
    r"^[A-Z][.)]\s+\S",
    # ALL-CAPS title line, on its own and not a sentence: "SCOPE OF WORK"
    r"^[A-Z0-9][A-Z0-9 \t&/,'()\-]{2,79}$",
)


class StructuralChunker:
    """Split per-page text into the sections its own markup marks out.

    Takes a :class:`~dtos.requests.StructuralChunkingRequest` to override the
    heading patterns or the size bounds; constructed bare it uses the built-in
    markers, which is what ``/process`` does unless the caller says otherwise.
    """

    def __init__(self, request: StructuralChunkingRequest | None = None) -> None:
        request = request or StructuralChunkingRequest()
        patterns = request.heading_patterns
        if patterns is None:
            patterns = list(_DEFAULT_HEADING_PATTERNS)
        # The request validated that each pattern compiles.
        self._headings = [re.compile(pattern) for pattern in patterns]
        self._min_words = request.min_words
        self._max_words = request.max_words

    def chunk(self, pages: list[str]) -> list[str]:
        return [text for _, text in self.chunk_with_pages(pages)]

    def chunk_with_pages(self, pages: list[str]) -> list[tuple[int, str]]:
        """Split ``pages`` into sections, tagging each with its start page.

        A section can span a page boundary; the reported page is the one holding
        the section's first line of text.
        """
        lines = self._flatten(pages)
        sections = self._split_at_headings(lines)
        if sections is None:
            # Nothing in the document is marked up, so paragraphs are the only
            # structure left to go on.
            sections = self._split_at_paragraphs(lines)
        return [
            chunk
            for section in self._merge_undersized(sections)
            for chunk in self._split_oversized(section)
        ]

    @staticmethod
    def _flatten(pages: list[str]) -> list[_Line]:
        """Pages to ``(line, page number)`` pairs, keeping the blank lines.

        Blank lines are the paragraph boundaries the fallback and the oversize
        split need, so they are carried through rather than filtered out here.
        """
        lines: list[_Line] = []
        for page_number, text in enumerate(pages, start=1):
            lines.extend((line.rstrip(), page_number) for line in text.splitlines())
        return lines

    def _is_heading(self, line: str) -> bool:
        stripped = line.strip()
        return bool(stripped) and any(
            pattern.search(stripped) for pattern in self._headings
        )

    def _split_at_headings(self, lines: list[_Line]) -> list[_Section] | None:
        """Group lines into one section per heading, or ``None`` if none matched.

        Text before the first heading becomes its own section, so a preamble is
        never swallowed by the section that follows it.
        """
        sections: list[_Section] = []
        current: _Section = []
        found = False
        for line in lines:
            if self._is_heading(line[0]):
                found = True
                if self._has_text(current):
                    sections.append(current)
                    current = []
            current.append(line)
        if current:
            sections.append(current)
        if not found:
            return None
        return [section for section in sections if self._has_text(section)]

    @staticmethod
    def _split_at_paragraphs(lines: list[_Line]) -> list[_Section]:
        """Group lines into paragraphs, dropping the blank lines between them."""
        sections: list[_Section] = []
        current: _Section = []
        for line in lines:
            if line[0].strip():
                current.append(line)
            elif current:
                sections.append(current)
                current = []
        if current:
            sections.append(current)
        return sections

    def _merge_undersized(self, sections: list[_Section]) -> list[_Section]:
        """Fold sections below ``min_words`` into the one that follows them.

        A heading with no body of its own is the common case: alone it is a chunk
        that says nothing, and it belongs with the section it titles. A trailing
        short section has nothing after it to join, so it goes to the previous one.
        """
        merged: list[_Section] = []
        pending: _Section = []
        for section in sections:
            candidate = self._concat(pending, section)
            if self._word_count(candidate) < self._min_words:
                pending = candidate
                continue
            merged.append(candidate)
            pending = []
        if pending:
            if merged:
                merged[-1] = self._concat(merged[-1], pending)
            else:
                # The whole document is shorter than the minimum: one chunk.
                merged.append(pending)
        return merged

    @staticmethod
    def _concat(left: _Section, right: _Section) -> _Section:
        """Join two sections, keeping a blank line between them as a separator."""
        if not left:
            return list(right)
        return [*left, ("", right[0][1]), *right]

    def _split_oversized(self, section: _Section) -> list[tuple[int, str]]:
        """Cut a section down to at most ``max_words`` per chunk.

        Splits at the coarsest boundary that fits — paragraphs first, then
        sentences — so an over-long section keeps as much of its shape as the cap
        allows.
        """
        if self._word_count(section) <= self._max_words:
            return [self._render(section)]

        chunks: list[tuple[int, str]] = []
        for paragraph in self._split_at_paragraphs(section):
            if self._word_count(paragraph) <= self._max_words:
                chunks.append(self._render(paragraph))
            else:
                chunks.extend(self._split_at_sentences(paragraph))
        return chunks

    def _split_at_sentences(self, paragraph: _Section) -> list[tuple[int, str]]:
        """Split one over-long paragraph at sentence boundaries.

        Sentences are packed up to the cap; one sentence longer than the cap on
        its own is cut into fixed word windows, the only boundary left below a
        sentence.
        """
        # Sentences span lines, so walk the paragraph's words alongside them to
        # know which page each sentence starts on.
        words = [(word, page) for line, page in paragraph for word in line.split()]
        text = " ".join(line.strip() for line, _ in paragraph)

        chunks: list[tuple[int, str]] = []
        group: list[str] = []
        group_page = 0
        group_words = 0
        cursor = 0
        for sentence in split_sentences(text):
            length = len(sentence.split())
            page = words[cursor][1]
            cursor += length

            if group and (
                length > self._max_words or group_words + length > self._max_words
            ):
                chunks.append((group_page, " ".join(group)))
                group, group_words = [], 0
            if length > self._max_words:
                chunks.extend(self._split_at_words(sentence, page))
                continue
            if not group:
                group_page = page
            group.append(sentence)
            group_words += length
        if group:
            chunks.append((group_page, " ".join(group)))
        return chunks

    def _split_at_words(self, sentence: str, page: int) -> list[tuple[int, str]]:
        """Last resort: cut a single over-long sentence into fixed word windows."""
        words = sentence.split()
        return [
            (page, " ".join(words[start : start + self._max_words]))
            for start in range(0, len(words), self._max_words)
        ]

    @staticmethod
    def _render(section: _Section) -> tuple[int, str]:
        """Join a section into a chunk tagged with the page its text starts on.

        Line breaks are kept — the heading reads as a heading in a retrieval
        result — but leading/trailing blank lines are dropped and runs of blank
        lines collapse to one, so the chunk carries the document's structure and
        not the gaps its extracted text happened to have.
        """
        rendered: list[str] = []
        for line, _ in section:
            if line.strip():
                rendered.append(line.strip())
            elif rendered and rendered[-1]:
                rendered.append("")
        while rendered and not rendered[-1]:
            rendered.pop()
        page = next(page for line, page in section if line.strip())
        return page, "\n".join(rendered)

    @staticmethod
    def _has_text(section: _Section) -> bool:
        return any(line.strip() for line, _ in section)

    @staticmethod
    def _word_count(section: _Section) -> int:
        return sum(len(line.split()) for line, _ in section)
