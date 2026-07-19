"""Ollama text-generation backend (generation stage).

Calls a locally running Ollama server to complete a prompt. The server URL and
model come from config/env, never hardcoded (see CLAUDE.md): :meth:`OllamaClient.from_env`
reads ``OLLAMA_BASE_URL`` and ``OLLAMA_MODEL``. The docker-compose stack runs the
server and pulls the default model.
"""

import os

from ollama import Client

_BASE_URL_ENV_VAR = "OLLAMA_BASE_URL"
_MODEL_ENV_VAR = "OLLAMA_MODEL"
_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "gemma2:2b"

# Low temperature keeps answers close to the provided context (less invention).
_TEMPERATURE = 0.2


class OllamaClient:
    """Generate completions with a model served by Ollama."""

    def __init__(self, model: str, base_url: str = _DEFAULT_BASE_URL) -> None:
        self._model = model
        self._client = Client(host=base_url)

    @classmethod
    def from_env(cls) -> "OllamaClient":
        """Build a client from ``$OLLAMA_BASE_URL`` and ``$OLLAMA_MODEL``.

        Both fall back to the docker-compose defaults (localhost:11434, gemma2:2b).
        """
        return cls(
            model=os.environ.get(_MODEL_ENV_VAR, _DEFAULT_MODEL),
            base_url=os.environ.get(_BASE_URL_ENV_VAR, _DEFAULT_BASE_URL),
        )

    def generate(self, prompt: str) -> str:
        """Return the model's completion for ``prompt`` (non-streaming)."""
        response = self._client.generate(
            model=self._model,
            prompt=prompt,
            stream=False,
            options={"temperature": _TEMPERATURE},
        )
        # ``response`` is Optional in the ollama types; treat a missing body as "".
        return (response.response or "").strip()
