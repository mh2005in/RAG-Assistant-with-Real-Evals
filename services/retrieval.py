"""Retrieval service.

Everything behind the ``/retrieve`` endpoint: embed the query text with the same
model used to store chunks, then run a pgvector similarity search over the stored
chunks (filtered by access role). Route handlers stay thin and delegate here (see
CLAUDE.md).

The vector search SQL itself lives on :class:`~services.storage.PostgresStorage`
(it owns the ``chunks`` table); this service only orchestrates embedding + search.
"""

from dtos.requests import RetrievalRequest
from dtos.responses import RetrievalResponse
from services.embedding import Embedder, OllamaEmbedder
from services.storage import PostgresStorage


class Retrieval:
    """Embed a query and search stored chunks for the closest matches.

    The embedder loads its model lazily on first use, so constructing the service
    (and importing the app) stays cheap until a query is actually run. Pass an
    ``embedder`` to override the model/device or to inject a fake in tests.
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = OllamaEmbedder.from_env()
        return self._embedder

    def retrieve(
        self, request: RetrievalRequest, storage: PostgresStorage
    ) -> RetrievalResponse:
        """Embed ``request.query`` and return the top-k most similar chunks.

        The query is embedded with the default model, so it must match the model
        the stored chunks were embedded with (same vector dimension).
        """
        query_embedding = self._get_embedder().embed([request.query])[0]
        results = storage.search_chunks(
            query_embedding, request.access_role, request.top_k
        )
        return RetrievalResponse(
            query=request.query, count=len(results), results=results
        )
