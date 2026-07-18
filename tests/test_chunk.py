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


def test_truncated_clips_text_and_embedding_but_keeps_stats() -> None:
    text = "abcdefghij"
    chunk = Chunk.from_page(2, text)
    chunk.embedding = [float(i) for i in range(10)]

    preview = chunk.truncated(text_chars=4, embedding_dims=3)

    # Bulky payloads are clipped.
    assert preview.text == "abcd"
    assert preview.embedding == [0.0, 1.0, 2.0]
    # Stats still describe the full page and vector; the original is untouched.
    assert preview.page_number == 2
    assert preview.page_char_count == len(text)
    assert chunk.text == text
    assert chunk.embedding == [float(i) for i in range(10)]


def test_truncated_leaves_short_text_and_embedding_unchanged() -> None:
    chunk = Chunk.from_page(1, "short")
    chunk.embedding = [1.0, 2.0]

    preview = chunk.truncated(text_chars=200, embedding_dims=8)

    assert preview.text == "short"
    assert preview.embedding == [1.0, 2.0]
