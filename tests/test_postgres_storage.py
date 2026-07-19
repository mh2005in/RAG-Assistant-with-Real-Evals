"""Tests for the PostgreSQL/pgvector storage service.

The unit tests never touch a database: they drive :class:`PostgresStorage` with a
mocked connection and assert on the exact SQL and parameters it issues, keeping
the default run fast and offline (see CLAUDE.md).

The ``integration`` test at the bottom needs a live PostgreSQL/pgvector database
with ``db/schema.sql`` already applied; it is skipped unless ``DATABASE_URL`` is
set.
"""

import os
from unittest.mock import MagicMock

import pytest
from pgvector import Vector

import services.storage.postgres as postgres_module
from dtos.responses import Chunk
from services.storage import PostgresStorage
from services.storage.postgres import _INSERT_CHUNK, _INSERT_DOCUMENT


def _mock_connection(document_id: int = 42) -> tuple[MagicMock, MagicMock]:
    """A mocked connection whose cursor returns ``document_id`` for the insert."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (document_id,)
    return conn, cursor


def _embedded(page_number: int, text: str, embedding: list[float]) -> Chunk:
    return Chunk.from_page(page_number, text).model_copy(
        update={"embedding": embedding}
    )


def test_insert_document_writes_document_then_chunks() -> None:
    conn, cursor = _mock_connection(document_id=7)
    chunks = [
        _embedded(1, "alpha beta", [0.1, 0.2]),
        _embedded(3, "gamma", [0.3, 0.4]),
    ]

    result = PostgresStorage(conn).insert_document("doc.pdf", "analyst", chunks)

    assert result.document_id == 7
    assert result.chunk_count == 2

    # The document row is inserted first, returning its id.
    cursor.execute.assert_called_once_with(_INSERT_DOCUMENT, ("doc.pdf", "analyst"))

    # Chunks are inserted in one batch, keyed to the new document id and numbered
    # 0, 1, ... with their embeddings wrapped as pgvector Vectors.
    sql, rows = cursor.executemany.call_args.args
    assert sql == _INSERT_CHUNK
    assert rows[0] == (
        7,
        0,
        1,
        chunks[0].page_char_count,
        chunks[0].page_word_count,
        chunks[0].page_sentence_count_raw,
        chunks[0].page_token_count,
        "alpha beta",
        Vector([0.1, 0.2]),
    )
    assert rows[1][:3] == (7, 1, 3)
    assert rows[1][8] == Vector([0.3, 0.4])


def test_insert_document_is_wrapped_in_a_transaction() -> None:
    conn, _ = _mock_connection()

    PostgresStorage(conn).insert_document("doc.pdf", "analyst", [])

    conn.transaction.assert_called_once_with()


def test_unembedded_chunk_is_stored_as_null() -> None:
    conn, cursor = _mock_connection()
    # A chunk that has not been embedded carries an empty embedding.
    chunks = [Chunk.from_page(1, "not embedded")]

    PostgresStorage(conn).insert_document("doc.pdf", "analyst", chunks)

    _, rows = cursor.executemany.call_args.args
    assert rows[0][8] is None


def test_insert_document_with_no_chunks_skips_chunk_insert() -> None:
    conn, cursor = _mock_connection(document_id=99)

    result = PostgresStorage(conn).insert_document("empty.pdf", "analyst", [])

    assert result.document_id == 99
    assert result.chunk_count == 0
    cursor.executemany.assert_not_called()


def test_missing_returned_id_raises() -> None:
    conn, cursor = _mock_connection()
    cursor.fetchone.return_value = None

    with pytest.raises(RuntimeError, match="did not return an id"):
        PostgresStorage(conn).insert_document("doc.pdf", "analyst", [])


def test_connect_requires_a_connection_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="DATABASE_URL"):
        PostgresStorage.connect()


def test_connect_reads_env_and_registers_pgvector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = MagicMock()
    connect_mock = MagicMock(return_value=fake_conn)
    register_mock = MagicMock()
    monkeypatch.setattr(postgres_module.psycopg, "connect", connect_mock)
    monkeypatch.setattr(postgres_module, "register_vector", register_mock)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

    storage = PostgresStorage.connect()

    connect_mock.assert_called_once_with("postgresql://localhost/test")
    register_mock.assert_called_once_with(fake_conn)
    assert storage._conn is fake_conn


@pytest.mark.integration
def test_insert_and_read_back_roundtrip() -> None:
    """Insert a document + chunk into a real database and read it back.

    Requires ``DATABASE_URL`` pointing at a PostgreSQL/pgvector database with
    ``db/schema.sql`` applied. Cleans up after itself (cascade delete).
    """
    conn_str = os.environ.get("DATABASE_URL")
    if not conn_str:
        pytest.skip("DATABASE_URL not set; skipping database integration test")

    storage = PostgresStorage.connect(conn_str)
    try:
        chunk = _embedded(1, "integration text", [0.1] * 768)
        result = storage.insert_document("integration-doc", "tester", [chunk])
        assert result.chunk_count == 1

        with storage._conn.cursor() as cur:
            cur.execute(
                "SELECT name, access_role FROM documents WHERE id = %s",
                (result.document_id,),
            )
            assert cur.fetchone() == ("integration-doc", "tester")

            cur.execute(
                "SELECT chunk_index, text, embedding FROM chunks "
                "WHERE document_id = %s",
                (result.document_id,),
            )
            rows = cur.fetchall()
            assert len(rows) == 1
            index, text, embedding = rows[0]
            assert index == 0
            assert text == "integration text"
            assert len(embedding.to_list()) == 768

            cur.execute("DELETE FROM documents WHERE id = %s", (result.document_id,))
        storage._conn.commit()
    finally:
        storage.close()
