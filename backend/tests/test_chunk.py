"""Tests for the Chunk DTO and its per-page stat computation."""

from dtos.responses import Chunk


def test_from_page_computes_stats() -> None:
    chunk = Chunk.from_page(3, "Hello world. This is text.")

    assert chunk.page_number == 3
    assert chunk.text == "Hello world. This is text."
    assert chunk.page_char_count == 26
    assert chunk.page_word_count == 5
    # "Hello world" and "This is text." -> two naive sentences.
    assert chunk.page_sentence_count_raw == 2
    assert chunk.page_token_count == 26 / 4
    # Not embedded yet.
    assert chunk.embedding == []


def test_from_page_empty_text_is_all_zero() -> None:
    chunk = Chunk.from_page(1, "")

    assert chunk.page_char_count == 0
    assert chunk.page_word_count == 0
    assert chunk.page_sentence_count_raw == 0
    assert chunk.page_token_count == 0


def test_from_page_whitespace_only_counts_no_words_or_sentences() -> None:
    chunk = Chunk.from_page(1, "   \n  ")

    assert chunk.page_word_count == 0
    assert chunk.page_sentence_count_raw == 0
