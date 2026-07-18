"""Shared pytest fixtures.

Provides a small in-memory PDF builder so tests can exercise real PDF
extraction without any files on disk or network access, and a fake
sentence-transformers model so the embedding path runs offline (see CLAUDE.md).
"""

from collections.abc import Callable
from typing import Any

import numpy as np
import pymupdf
import pytest


class FakeSentenceTransformer:
    """Stand-in for ``SentenceTransformer``: records init args, fakes encode.

    Loads no weights and hits no network. ``encode`` returns a deterministic
    2-d vector per text so ordering and pass-through are verifiable.
    """

    instances: list["FakeSentenceTransformer"] = []

    def __init__(self, model_name: str, device: str) -> None:
        self.model_name = model_name
        self.device = device
        FakeSentenceTransformer.instances.append(self)

    def encode(self, texts: list[str], convert_to_numpy: bool = True) -> Any:
        return np.array([[float(len(text)), float(i)] for i, text in enumerate(texts)])


@pytest.fixture(autouse=True)
def fake_embedder_model(
    monkeypatch: pytest.MonkeyPatch,
) -> type[FakeSentenceTransformer]:
    """Replace the real model with a fake everywhere, keeping tests offline."""
    FakeSentenceTransformer.instances = []
    monkeypatch.setattr(
        "services.embedding.sentence_transformer.SentenceTransformer",
        FakeSentenceTransformer,
    )
    return FakeSentenceTransformer


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
