"""Tests for the Ollama generation client (no server is contacted).

The ollama ``Client`` is replaced with a fake, so nothing hits the network.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import services.generation.ollama_client as ollama_module
from services.generation import OllamaClient


def test_generate_passes_prompt_and_strips_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    fake_client.generate.return_value = SimpleNamespace(response="  the answer  ")
    monkeypatch.setattr(ollama_module, "Client", MagicMock(return_value=fake_client))

    result = OllamaClient(model="gpt-oss:20b").generate("a prompt")

    assert result == "the answer"
    kwargs = fake_client.generate.call_args.kwargs
    assert kwargs["model"] == "gpt-oss:20b"
    assert kwargs["prompt"] == "a prompt"
    assert kwargs["stream"] is False


def test_generate_handles_missing_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    fake_client.generate.return_value = SimpleNamespace(response=None)
    monkeypatch.setattr(ollama_module, "Client", MagicMock(return_value=fake_client))

    assert OllamaClient(model="gpt-oss:20b").generate("p") == ""


def test_from_env_reads_model_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_ctor(host: str | None = None, **kwargs: Any) -> MagicMock:
        captured["host"] = host
        return MagicMock()

    monkeypatch.setattr(ollama_module, "Client", fake_ctor)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:1234")

    client = OllamaClient.from_env()

    assert client._model == "llama3.2:3b"
    assert captured["host"] == "http://example:1234"


def test_from_env_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(ollama_module, "Client", MagicMock())

    assert OllamaClient.from_env()._model == "gpt-oss:20b"
