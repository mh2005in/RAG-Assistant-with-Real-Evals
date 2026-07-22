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
from services.storage.postgres import (
    _DELETE_DOCUMENT_CHUNKS,
    _DELETE_LOSING_CHUNKS,
    _INSERT_CHUNK,
    _INSERT_DOCUMENT_IF_NEW,
    _SEARCH_CHUNKS,
    _SELECT_DOCUMENT_ID,
)


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

    result = PostgresStorage(conn).insert_document(
        "doc.pdf", "analyst", {"fixed": chunks}
    )

    assert result.document_id == 7
    assert result.chunk_count == 2

    # The document row is created if new (one row per document), then whatever
    # it held before is cleared out.
    assert cursor.execute.call_args_list[0].args == (
        _INSERT_DOCUMENT_IF_NEW,
        ("doc.pdf", "analyst"),
    )
    assert cursor.execute.call_args_list[1].args == (_DELETE_DOCUMENT_CHUNKS, (7,))

    # Chunks are inserted in one batch, keyed to the new document id and numbered
    # 0, 1, ... with their embeddings wrapped as pgvector Vectors.
    sql, rows = cursor.executemany.call_args.args
    assert sql == _INSERT_CHUNK
    assert rows[0] == (
        7,
        "fixed",
        0,
        1,
        chunks[0].page_char_count,
        chunks[0].page_word_count,
        chunks[0].page_sentence_count_raw,
        chunks[0].page_token_count,
        "alpha beta",
        Vector([0.1, 0.2]),
    )
    assert rows[1][:4] == (7, "fixed", 1, 3)
    assert rows[1][9] == Vector([0.3, 0.4])


def test_insert_document_is_wrapped_in_a_transaction() -> None:
    conn, _ = _mock_connection()

    PostgresStorage(conn).insert_document("doc.pdf", "analyst", {})

    conn.transaction.assert_called_once_with()


def test_unembedded_chunk_is_stored_as_null() -> None:
    conn, cursor = _mock_connection()
    # A chunk that has not been embedded carries an empty embedding.
    chunks = [Chunk.from_page(1, "not embedded")]

    PostgresStorage(conn).insert_document("doc.pdf", "analyst", {"fixed": chunks})

    _, rows = cursor.executemany.call_args.args
    assert rows[0][9] is None


def test_insert_document_with_no_chunks_skips_chunk_insert() -> None:
    conn, cursor = _mock_connection(document_id=99)

    result = PostgresStorage(conn).insert_document("empty.pdf", "analyst", {})

    assert result.document_id == 99
    assert result.chunk_count == 0
    cursor.executemany.assert_not_called()


def test_missing_returned_id_raises() -> None:
    conn, cursor = _mock_connection()
    cursor.fetchone.return_value = None

    with pytest.raises(RuntimeError, match="did not return an id"):
        PostgresStorage(conn).insert_document("doc.pdf", "analyst", {})


def test_search_chunks_runs_similarity_query_and_maps_rows() -> None:
    conn, cursor = _mock_connection()
    cursor.fetchall.return_value = [
        (7, "doc.pdf", "fixed", 0, 1, "alpha", 0.25),
        (7, "doc.pdf", "fixed", 1, 2, "beta", 0.5),
    ]

    results = PostgresStorage(conn).search_chunks([0.1, 0.2], "analyst", top_k=5)

    # The query vector is bound once (named param) and role/top_k passed through.
    sql, params = cursor.execute.call_args.args
    assert sql == _SEARCH_CHUNKS
    assert params == {
        "query": Vector([0.1, 0.2]),
        "access_role": "analyst",
        "top_k": 5,
        "chunking_strategy": None,
    }

    # Rows map to RetrievedChunk, and cosine distance becomes a 1 - d similarity.
    assert [(r.text, r.chunk_index, r.page_number) for r in results] == [
        ("alpha", 0, 1),
        ("beta", 1, 2),
    ]
    assert results[0].document_id == 7
    assert results[0].document_name == "doc.pdf"
    assert results[0].score == pytest.approx(0.75)
    assert results[1].score == pytest.approx(0.5)


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
        result = storage.insert_document(
            "integration-doc", "tester", {"fixed": [chunk]}
        )
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


@pytest.mark.integration
def test_search_ranks_by_similarity_and_filters_by_role() -> None:
    """Insert two chunks, search, and check ranking + the access-role filter.

    Requires ``DATABASE_URL`` (see the roundtrip test). Cleans up after itself.
    """
    conn_str = os.environ.get("DATABASE_URL")
    if not conn_str:
        pytest.skip("DATABASE_URL not set; skipping database integration test")

    near = [1.0] + [0.0] * 767
    far = [0.0, 1.0] + [0.0] * 766

    storage = PostgresStorage.connect(conn_str)
    try:
        stored = storage.insert_document(
            "search-doc",
            "searcher",
            {
                "fixed": [
                    _embedded(1, "near chunk", near),
                    _embedded(2, "far chunk", far),
                ]
            },
        )

        results = storage.search_chunks(near, "searcher", top_k=5)
        assert [r.text for r in results] == ["near chunk", "far chunk"]
        assert results[0].score > results[1].score
        assert results[0].document_name == "search-doc"

        # Role-based filter: a different role sees nothing.
        assert storage.search_chunks(near, "other-role", top_k=5) == []

        with storage._conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (stored.document_id,))
        storage._conn.commit()
    finally:
        storage.close()


@pytest.mark.integration
def test_reprocessing_a_document_keeps_one_row() -> None:
    """Processing the same document twice must not duplicate the documents row."""
    conn_str = os.environ.get("DATABASE_URL")
    if not conn_str:
        pytest.skip("DATABASE_URL not set; skipping database integration test")

    vector = [0.5] + [0.0] * 767

    storage = PostgresStorage.connect(conn_str)
    try:
        first = storage.insert_document(
            "dupe-doc", "dupe-tester", {"fixed": [_embedded(1, "first pass", vector)]}
        )
        second = storage.insert_document(
            "dupe-doc",
            "dupe-tester",
            {"semantic": [_embedded(1, "second pass", vector)]},
        )

        # Same row reused, and the old chunks replaced by the new ones.
        assert first.document_id == second.document_id
        with storage._conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM documents WHERE name = %s AND access_role = %s",
                ("dupe-doc", "dupe-tester"),
            )
            assert cur.fetchone() == (1,)
            cur.execute(
                "SELECT chunking_strategy, text FROM chunks WHERE document_id = %s",
                (second.document_id,),
            )
            assert cur.fetchall() == [("semantic", "second pass")]

            cur.execute("DELETE FROM documents WHERE id = %s", (second.document_id,))
        storage._conn.commit()
    finally:
        storage.close()


@pytest.mark.integration
def test_search_filters_by_chunking_strategy() -> None:
    """The strategy filter runs against a real database.

    A mocked cursor cannot catch SQL that Postgres rejects (e.g. a bare NULL
    parameter whose type it cannot infer), so this exercises both the unfiltered
    and filtered paths for real. Requires ``DATABASE_URL``; cleans up after itself.
    """
    conn_str = os.environ.get("DATABASE_URL")
    if not conn_str:
        pytest.skip("DATABASE_URL not set; skipping database integration test")

    vector = [1.0] + [0.0] * 767

    storage = PostgresStorage.connect(conn_str)
    try:
        stored = storage.insert_document(
            "strategy-doc",
            "strategy-tester",
            {
                "fixed": [_embedded(1, "fixed chunk", vector)],
                "semantic": [_embedded(1, "semantic chunk", vector)],
            },
        )

        # No filter searches every strategy (this is the NULL-parameter path).
        everything = storage.search_chunks(vector, "strategy-tester", top_k=10)
        assert {chunk.chunking_strategy for chunk in everything} == {
            "fixed",
            "semantic",
        }

        only_semantic = storage.search_chunks(
            vector, "strategy-tester", top_k=10, chunking_strategy="semantic"
        )
        assert [chunk.text for chunk in only_semantic] == ["semantic chunk"]

        # Dropping the losers leaves exactly one strategy behind.
        deleted = storage.delete_chunks_except(stored.document_id, "semantic")
        assert deleted == 1
        remaining = storage.search_chunks(vector, "strategy-tester", top_k=10)
        assert [chunk.chunking_strategy for chunk in remaining] == ["semantic"]

        with storage._conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (stored.document_id,))
        storage._conn.commit()
    finally:
        storage.close()


def test_insert_document_writes_every_strategys_chunks() -> None:
    conn, cursor = _mock_connection(document_id=7)

    result = PostgresStorage(conn).insert_document(
        "doc.pdf",
        "analyst",
        {
            "fixed": [Chunk.from_page(1, "a"), Chunk.from_page(1, "b")],
            "semantic": [Chunk.from_page(1, "c")],
        },
    )

    # One documents row holds all three chunks.
    assert result.chunk_count == 3
    _, rows = cursor.executemany.call_args.args
    assert [(row[1], row[2]) for row in rows] == [
        ("fixed", 0),
        ("fixed", 1),
        ("semantic", 0),  # numbering restarts per strategy
    ]


def test_delete_chunks_except_keeps_only_the_winner() -> None:
    conn, cursor = _mock_connection()
    cursor.rowcount = 4

    deleted = PostgresStorage(conn).delete_chunks_except(7, "semantic")

    assert deleted == 4
    cursor.execute.assert_called_once_with(_DELETE_LOSING_CHUNKS, (7, "semantic"))


def test_reprocessing_reuses_the_document_row_and_replaces_its_chunks() -> None:
    conn, cursor = _mock_connection(document_id=7)

    PostgresStorage(conn).insert_document(
        "doc.pdf", "analyst", {"semantic": [Chunk.from_page(1, "new")]}
    )

    # Insert-if-new, so the same document never gets a second row...
    sql, params = cursor.execute.call_args_list[0].args
    assert sql == _INSERT_DOCUMENT_IF_NEW
    assert params == ("doc.pdf", "analyst")
    assert "ON CONFLICT (name, access_role) DO NOTHING" in _INSERT_DOCUMENT_IF_NEW
    # ...and its previous chunks are cleared before the new ones land.
    assert cursor.execute.call_args_list[1].args == (_DELETE_DOCUMENT_CHUNKS, (7,))


def test_existing_document_row_is_read_back_never_written() -> None:
    conn, cursor = _mock_connection()
    # DO NOTHING returns no row when the document already exists; the id is then
    # read back with a plain SELECT.
    cursor.fetchone.side_effect = [None, (7,)]

    result = PostgresStorage(conn).insert_document("doc.pdf", "analyst", {})

    assert result.document_id == 7
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert statements[0] == _INSERT_DOCUMENT_IF_NEW
    assert statements[1] == _SELECT_DOCUMENT_ID
    # Nothing updates the documents row: it is immutable once created.
    assert not any("UPDATE documents" in sql for sql in statements)
