"""Tests for the sentence-transformers embedder.

The real model is never loaded: the autouse ``fake_embedder_model`` fixture (see
conftest) replaces ``SentenceTransformer`` with a fake that records how it was
constructed and returns canned vectors, keeping the tests fast and offline.
Tests that inspect the constructed model request the fixture to reach the fake.
"""

from typing import Any

from dtos.requests import DEFAULT_MODEL_NAME, Device, EmbeddingRequest
from dtos.responses import Chunk
from services.embedding import SentenceTransformerEmbedder


def test_defaults_to_all_mpnet_on_cpu(fake_embedder_model: Any) -> None:
    SentenceTransformerEmbedder()

    model = fake_embedder_model.instances[-1]
    assert model.model_name == DEFAULT_MODEL_NAME
    assert model.device == "cpu"


def test_passes_configured_model_and_device(fake_embedder_model: Any) -> None:
    request = EmbeddingRequest(model_name="custom/model", device=Device.cuda)

    SentenceTransformerEmbedder(request)

    model = fake_embedder_model.instances[-1]
    assert model.model_name == "custom/model"
    assert model.device == "cuda"


def test_embed_returns_one_vector_per_text_in_order() -> None:
    vectors = SentenceTransformerEmbedder().embed(["ab", "cde"])

    assert vectors == [[2.0, 0.0], [3.0, 1.0]]


def test_embed_empty_list_returns_empty() -> None:
    assert SentenceTransformerEmbedder().embed([]) == []


def test_embed_chunks_fills_embedding_and_preserves_stats() -> None:
    chunks = [Chunk.from_page(1, "ab"), Chunk.from_page(2, "cde")]

    embedded = SentenceTransformerEmbedder().embed_chunks(chunks)

    assert [chunk.embedding for chunk in embedded] == [[2.0, 0.0], [3.0, 1.0]]
    # Original stats are carried through untouched.
    assert embedded[0].page_number == 1
    assert embedded[1].page_char_count == 3
    # Inputs are not mutated.
    assert chunks[0].embedding == []
