"""PostgreSQL + pgvector storage service (storage stage).

Data access for the ``documents`` and ``chunks`` tables defined in
``db/schema.sql``: writes a document and its embedded chunks, and runs the
pgvector similarity search behind retrieval. Connection details come from
config/env, never hardcoded (see CLAUDE.md): :meth:`PostgresStorage.connect`
reads ``DATABASE_URL`` unless an explicit connection string is passed.

This owns the SQL against those tables; embedding the query text for a search is
orchestration and lives in the retrieval service.
"""

import os

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from dtos.responses import Chunk, RetrievedChunk, StoredDocument

_CONN_ENV_VAR = "DATABASE_URL"

# Insert statements kept as module constants so tests can assert against the
# exact SQL the service issues.
# Get-or-create. A document is identified by (name, access_role); the row itself
# never changes after creation, only its chunks do. DO NOTHING (rather than a
# no-op DO UPDATE) leaves an existing row completely untouched — updating it to
# the values it already holds would just write a dead row version for nothing.
# DO NOTHING returns no row on conflict, so the id is then read back.
_INSERT_DOCUMENT_IF_NEW = """
    INSERT INTO documents (name, access_role)
    VALUES (%s, %s)
    ON CONFLICT (name, access_role) DO NOTHING
    RETURNING id
"""
_SELECT_DOCUMENT_ID = "SELECT id FROM documents WHERE name = %s AND access_role = %s"
# Re-processing replaces a document's chunks outright, so a stale strategy or an
# older chunk_size cannot linger alongside the new ones.
_DELETE_DOCUMENT_CHUNKS = "DELETE FROM chunks WHERE document_id = %s"
_INSERT_CHUNK = """
    INSERT INTO chunks (
        document_id, chunking_strategy, chunk_index, page_number, page_char_count,
        page_word_count, page_sentence_count_raw, page_token_count,
        text, embedding
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
# Drop every strategy's chunks except the winner, once the strategies have been
# scored. The documents row and the winning chunks are untouched.
_DELETE_LOSING_CHUNKS = """
    DELETE FROM chunks
    WHERE document_id = %s
      AND chunking_strategy <> %s
"""
# Nearest-neighbour search by cosine distance (``<=>``), which matches the HNSW
# index in db/schema.sql. Restricted to the caller's access role and to chunks
# that have actually been embedded. The query vector is bound once as a named
# parameter and referenced in both the SELECT and the ORDER BY. A NULL
# ``chunking_strategy`` searches every strategy; setting it compares one.
_SEARCH_CHUNKS = """
    SELECT
        c.document_id,
        d.name AS document_name,
        c.chunking_strategy,
        c.chunk_index,
        c.page_number,
        c.text,
        c.embedding <=> %(query)s AS distance
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.access_role = %(access_role)s
      AND c.embedding IS NOT NULL
      -- Cast required: Postgres cannot infer a bare NULL parameter's type here.
      AND (%(chunking_strategy)s::text IS NULL
           OR c.chunking_strategy = %(chunking_strategy)s::text)
    ORDER BY c.embedding <=> %(query)s
    LIMIT %(top_k)s
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
        self,
        name: str,
        access_role: str,
        chunks_by_strategy: dict[str, list[Chunk]],
    ) -> StoredDocument:
        """Persist one document and every strategy's chunks in one transaction.

        The document is identified by ``(name, access_role)``: processing the same
        document again reuses its row — left untouched, since nothing about it
        changes — and replaces its chunks, so the table never accumulates
        duplicate entries for one document. Each strategy's chunks are
        attached to it, tagged with the strategy that produced them and numbered
        from 0 *within that strategy*. Storing the candidates side by side is what
        lets them be compared before one is kept (see
        :meth:`delete_chunks_except`).

        A chunk's ``embedding`` is stored as a ``vector`` when present and left
        NULL when it has not been embedded yet. The whole write is atomic: on any
        failure nothing is committed.
        """
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(_INSERT_DOCUMENT_IF_NEW, (name, access_role))
            row = cur.fetchone()
            if row is None:
                # The document already exists; read its id without touching it.
                cur.execute(_SELECT_DOCUMENT_ID, (name, access_role))
                row = cur.fetchone()
            if row is None:
                raise RuntimeError("document insert did not return an id")
            document_id = int(row[0])

            # Replace whatever this document held before.
            cur.execute(_DELETE_DOCUMENT_CHUNKS, (document_id,))

            rows = [
                self._chunk_row(document_id, strategy, index, chunk)
                for strategy, chunks in chunks_by_strategy.items()
                for index, chunk in enumerate(chunks)
            ]
            if rows:
                cur.executemany(_INSERT_CHUNK, rows)

        return StoredDocument(document_id=document_id, chunk_count=len(rows))

    def delete_chunks_except(self, document_id: int, keep_strategy: str) -> int:
        """Delete the document's chunks from every strategy but ``keep_strategy``.

        Returns how many chunk rows were removed. The ``documents`` row and the
        winning strategy's chunks are left alone.
        """
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(_DELETE_LOSING_CHUNKS, (document_id, keep_strategy))
            return cur.rowcount

    def search_chunks(
        self,
        query_embedding: list[float],
        access_role: str,
        top_k: int,
        chunking_strategy: str | None = None,
    ) -> list[RetrievedChunk]:
        """Return the ``top_k`` chunks most similar to ``query_embedding``.

        Searches only chunks belonging to documents with ``access_role`` (the
        role-based access filter) and ranks them by cosine distance. The raw
        cosine distance is converted to a similarity score (``1 - distance``) so
        higher means closer. ``query_embedding`` must have the same dimension as
        the stored vectors (the embedding model must match the one used to store).

        ``chunking_strategy`` restricts the search to chunks produced by that
        strategy; ``None`` searches every strategy.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                _SEARCH_CHUNKS,
                {
                    "query": Vector(query_embedding),
                    "access_role": access_role,
                    "top_k": top_k,
                    "chunking_strategy": chunking_strategy,
                },
            )
            rows = cur.fetchall()
        return [
            RetrievedChunk(
                document_id=document_id,
                document_name=document_name,
                chunking_strategy=chunking_strategy_value,
                chunk_index=chunk_index,
                page_number=page_number,
                text=text,
                score=1.0 - float(distance),
            )
            for (
                document_id,
                document_name,
                chunking_strategy_value,
                chunk_index,
                page_number,
                text,
                distance,
            ) in rows
        ]

    @staticmethod
    def _chunk_row(
        document_id: int, chunking_strategy: str, index: int, chunk: Chunk
    ) -> tuple[object, ...]:
        """Flatten a chunk into positional params for ``_INSERT_CHUNK``."""
        return (
            document_id,
            chunking_strategy,
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
