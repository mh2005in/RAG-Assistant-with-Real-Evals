"""Tests for the Ollama embedder (no server is contacted).

The ollama ``Client`` is replaced with a fake, so nothing hits the network.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import services.embedding.ollama_embedder as ollama_embedder_module
from dtos.responses import Chunk
from services.embedding import OllamaEmbedder


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake_client: MagicMock) -> None:
    monkeypatch.setattr(
        ollama_embedder_module, "Client", MagicMock(return_value=fake_client)
    )


def test_embed_returns_one_vector_per_text_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    fake_client.embed.return_value = SimpleNamespace(
        embeddings=[[1.0, 2.0], [3.0, 4.0]]
    )
    _patch_client(monkeypatch, fake_client)

    vectors = OllamaEmbedder(model="nomic-embed-text").embed(["ab", "cde"])

    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    kwargs = fake_client.embed.call_args.kwargs
    assert kwargs["model"] == "nomic-embed-text"
    assert kwargs["input"] == ["ab", "cde"]


def test_embed_empty_list_returns_empty_without_calling_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    _patch_client(monkeypatch, fake_client)

    assert OllamaEmbedder(model="m").embed([]) == []
    fake_client.embed.assert_not_called()


def test_embed_chunks_fills_embedding_and_preserves_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    fake_client.embed.return_value = SimpleNamespace(
        embeddings=[[1.0, 2.0], [3.0, 4.0]]
    )
    _patch_client(monkeypatch, fake_client)

    chunks = [Chunk.from_page(1, "ab"), Chunk.from_page(2, "cde")]
    embedded = OllamaEmbedder(model="m").embed_chunks(chunks)

    assert [chunk.embedding for chunk in embedded] == [[1.0, 2.0], [3.0, 4.0]]
    # Original stats are carried through untouched.
    assert embedded[0].page_number == 1
    assert embedded[1].page_char_count == 3
    # Inputs are not mutated.
    assert chunks[0].embedding == []


def test_from_env_reads_model_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_ctor(host: str | None = None, **kwargs: Any) -> MagicMock:
        captured["host"] = host
        return MagicMock()

    monkeypatch.setattr(ollama_embedder_module, "Client", fake_ctor)
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:1234")

    embedder = OllamaEmbedder.from_env()

    assert embedder._model == "mxbai-embed-large"
    assert captured["host"] == "http://example:1234"


def test_from_env_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(ollama_embedder_module, "Client", MagicMock())

    assert OllamaEmbedder.from_env()._model == "nomic-embed-text"
