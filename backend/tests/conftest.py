"""Shared pytest fixtures.

Provides in-memory PDF and DOCX builders so tests can exercise real extraction
without any files on disk or network access, and a fake Ollama client so the
embedding path runs offline (see CLAUDE.md).
"""

from collections.abc import Callable
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest
from docx import Document


class FakeOllamaEmbedClient:
    """Stand-in for ``ollama.Client`` used by ``OllamaEmbedder``.

    Loads nothing and hits no network. ``embed`` returns a deterministic 2-d
    vector per input text (``[len(text), position]``) so ordering and
    pass-through are verifiable.
    """

    def __init__(self, host: str | None = None, **kwargs: Any) -> None:
        self.host = host

    def embed(self, model: str, input: list[str]) -> Any:
        texts = [input] if isinstance(input, str) else list(input)
        embeddings = [[float(len(text)), float(i)] for i, text in enumerate(texts)]
        return SimpleNamespace(embeddings=embeddings)


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the embedder's Ollama client with a fake, keeping tests offline."""
    monkeypatch.setattr(
        "services.embedding.ollama_embedder.Client", FakeOllamaEmbedClient
    )


@pytest.fixture
def make_pdf() -> Callable[[list[str]], bytes]:
    """Return a factory that builds a PDF (as bytes) from per-page text."""

    def _build(pages: list[str]) -> bytes:
        doc = pymupdf.open()
        try:
            for text in pages:
                page = doc.new_page()
                page.insert_text((72, 72), text)
            return doc.tobytes()
        finally:
            doc.close()

    return _build


@pytest.fixture
def make_docx() -> Callable[[list[str]], bytes]:
    """Return a factory that builds a DOCX (as bytes) from its paragraphs.

    Real package bytes rather than a stub, so the extractor is exercised against
    a file python-docx would actually be handed.
    """

    def _build(paragraphs: list[str]) -> bytes:
        document = Document()
        for text in paragraphs:
            document.add_paragraph(text)
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    return _build
