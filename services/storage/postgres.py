"""PostgreSQL + pgvector storage service (storage stage).

Persists a document and its embedded chunks into the schema defined in
``db/schema.sql`` (the ``documents`` and ``chunks`` tables). Connection details
come from config/env, never hardcoded (see CLAUDE.md): :meth:`PostgresStorage.connect`
reads ``DATABASE_URL`` unless an explicit connection string is passed.

Retrieval (similarity search) is a separate concern and lives elsewhere; this
service only writes.
"""

import os

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from dtos.responses import Chunk, StoredDocument

_CONN_ENV_VAR = "DATABASE_URL"

# Insert statements kept as module constants so tests can assert against the
# exact SQL the service issues.
_INSERT_DOCUMENT = (
    "INSERT INTO documents (name, access_role) VALUES (%s, %s) RETURNING id"
)
_INSERT_CHUNK = """
    INSERT INTO chunks (
        document_id, chunk_index, page_number, page_char_count,
        page_word_count, page_sentence_count_raw, page_token_count,
        text, embedding
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class PostgresStorage:
    """Insert documents and their chunks into PostgreSQL/pgvector.

    Wraps a live :class:`psycopg.Connection`. Inject one directly (e.g. a fake in
    tests) or build one from config via :meth:`connect`, which also registers the
    pgvector adapters so embeddings round-trip as ``vector`` values.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection

    @classmethod
    def connect(cls, conn_str: str | None = None) -> "PostgresStorage":
        """Open a connection from ``conn_str`` or ``$DATABASE_URL`` and wrap it.

        Registers the pgvector type adapters on the connection so ``Vector``
        values can be passed straight through as ``vector`` parameters.
        """
        conn_str = conn_str or os.environ.get(_CONN_ENV_VAR)
        if not conn_str:
            raise ValueError(
                f"no database connection string provided; pass one or set "
                f"${_CONN_ENV_VAR}"
            )
        connection = psycopg.connect(conn_str)
        register_vector(connection)
        return cls(connection)

    def insert_document(
        self, name: str, access_role: str, chunks: list[Chunk]
    ) -> StoredDocument:
        """Persist a document and its chunks in one transaction.

        Inserts the ``documents`` row, then every chunk keyed to the new document
        id and numbered by position (``chunk_index`` 0, 1, 2, ...). A chunk's
        ``embedding`` is stored as a ``vector`` when present and left NULL when it
        has not been embedded yet. The whole write is atomic: on any failure
        nothing is committed.
        """
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(_INSERT_DOCUMENT, (name, access_role))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("document insert did not return an id")
            document_id = int(row[0])

            if chunks:
                cur.executemany(
                    _INSERT_CHUNK,
                    [
                        self._chunk_row(document_id, index, chunk)
                        for index, chunk in enumerate(chunks)
                    ],
                )

        return StoredDocument(document_id=document_id, chunk_count=len(chunks))

    @staticmethod
    def _chunk_row(document_id: int, index: int, chunk: Chunk) -> tuple[object, ...]:
        """Flatten a chunk into positional params for ``_INSERT_CHUNK``."""
        return (
            document_id,
            index,
            chunk.page_number,
            chunk.page_char_count,
            chunk.page_word_count,
            chunk.page_sentence_count_raw,
            chunk.page_token_count,
            chunk.text,
            # An un-embedded chunk (empty vector) is stored as NULL rather than a
            # zero-length vector, which would not match the column's dimension.
            Vector(chunk.embedding) if chunk.embedding else None,
        )

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()
