"""Ollama embedding strategy (embedding stage).

Embeds chunk text with a model served by a local Ollama server, so embedding runs
locally with no torch/HuggingFace dependency and shares the same server as the
generation stage. The server URL and model come from config/env, never hardcoded
(see CLAUDE.md): :meth:`OllamaEmbedder.from_env` reads ``OLLAMA_BASE_URL`` and
``OLLAMA_EMBED_MODEL``.

The default model, ``nomic-embed-text``, produces 768-dim vectors, matching the
``embedding vector(768)`` column in db/schema.sql.
"""

import os

from ollama import Client

from dtos.responses import Chunk

_BASE_URL_ENV_VAR = "OLLAMA_BASE_URL"
_MODEL_ENV_VAR = "OLLAMA_EMBED_MODEL"
_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "nomic-embed-text"


class OllamaEmbedder:
    """Embed text with an Ollama embedding model.

    One instance holds a client to the server; reuse it across calls. Build one
    from config with :meth:`from_env` or pass an explicit model/URL.
    """

    def __init__(
        self, model: str = _DEFAULT_MODEL, base_url: str = _DEFAULT_BASE_URL
    ) -> None:
        self._model = model
        self._client = Client(host=base_url)

    @classmethod
    def from_env(cls) -> "OllamaEmbedder":
        """Build an embedder from ``$OLLAMA_EMBED_MODEL`` and ``$OLLAMA_BASE_URL``.

        Both fall back to the docker-compose defaults (nomic-embed-text,
        localhost:11434).
        """
        return cls(
            model=os.environ.get(_MODEL_ENV_VAR, _DEFAULT_MODEL),
            base_url=os.environ.get(_BASE_URL_ENV_VAR, _DEFAULT_BASE_URL),
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` into vectors, one per text in the same order."""
        if not texts:
            return []
        response = self._client.embed(model=self._model, input=texts)
        return [list(vector) for vector in response.embeddings]

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Return copies of ``chunks`` with their ``embedding`` filled in."""
        vectors = self.embed([chunk.text for chunk in chunks])
        return [
            chunk.model_copy(update={"embedding": vector})
            for chunk, vector in zip(chunks, vectors)
        ]
