"""sentence-transformers embedding strategy (embedding stage).

Loads a sentence-transformers model (all-mpnet-base-v2 by default) on the
configured device and encodes chunk text into vectors. The model and device are
configurable via :class:`~dtos.requests.EmbeddingRequest`.
"""

from sentence_transformers import SentenceTransformer

from dtos.requests import EmbeddingRequest
from dtos.responses import Chunk


class SentenceTransformerEmbedder:
    """Embed text with a sentence-transformers model.

    The model is loaded once at construction on the request's device; reuse a
    single instance across calls rather than reconstructing per batch.
    """

    def __init__(self, request: EmbeddingRequest | None = None) -> None:
        request = request or EmbeddingRequest()
        self._model = SentenceTransformer(
            request.model_name, device=request.device.value
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` into vectors, one per text in the same order."""
        if not texts:
            return []
        vectors = self._model.encode(texts, convert_to_numpy=True)
        return [vector.tolist() for vector in vectors]

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Return copies of ``chunks`` with their ``embedding`` filled in."""
        vectors = self.embed([chunk.text for chunk in chunks])
        return [
            chunk.model_copy(update={"embedding": vector})
            for chunk, vector in zip(chunks, vectors)
        ]
