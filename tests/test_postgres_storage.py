"""Tests for the PostgreSQL/pgvector storage service.

The unit tests never touch a database: they drive :class:`PostgresStorage` with a
mocked connection and assert on the exact SQL and parameters it issues, keeping
the default run fast and offline (see CLAUDE.md).

The ``integration`` tests need a live PostgreSQL/pgvector database with
``db/schema.sql`` already applied; they are skipped unless ``DATABASE_URL`` is set.
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
    _SELECT_CHUNK_TEXTS,
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


def _store(
    storage: PostgresStorage,
    name: str,
    access_role: str,
    chunks_by_strategy: dict[str, list[Chunk]],
) -> int:
    """Persist a document and its chunks the way :class:`FileProcessing` does.

    Creates the document row, then inserts each chunk one at a time (numbered per
    strategy). Returns the document id. Used by the integration tests so they
    exercise the same create-then-stream path the service uses.
    """
    document_id = storage.create_document(name, access_role)
    for strategy, chunks in chunks_by_strategy.items():
        for index, chunk in enumerate(chunks):
            storage.insert_chunk(document_id, strategy, index, chunk)
    return document_id


def test_create_document_creates_row_then_clears_old_chunks() -> None:
    conn, cursor = _mock_connection(document_id=7)

    document_id = PostgresStorage(conn).create_document("doc.pdf", "analyst")

    assert document_id == 7
    # The document row is created if new (one row per document), then whatever it
    # held before is cleared out, so re-processing replaces its chunks.
    assert cursor.execute.call_args_list[0].args == (
        _INSERT_DOCUMENT_IF_NEW,
        ("doc.pdf", "analyst"),
    )
    assert cursor.execute.call_args_list[1].args == (_DELETE_DOCUMENT_CHUNKS, (7,))


def test_create_document_is_wrapped_in_a_transaction() -> None:
    conn, _ = _mock_connection()

    PostgresStorage(conn).create_document("doc.pdf", "analyst")

    conn.transaction.assert_called_once_with()


def test_create_document_missing_returned_id_raises() -> None:
    conn, cursor = _mock_connection()
    cursor.fetchone.return_value = None

    with pytest.raises(RuntimeError, match="did not return an id"):
        PostgresStorage(conn).create_document("doc.pdf", "analyst")


def test_create_document_reads_existing_id_and_never_writes_the_row() -> None:
    conn, cursor = _mock_connection()
    # DO NOTHING returns no row when the document already exists; the id is then
    # read back with a plain SELECT.
    cursor.fetchone.side_effect = [None, (7,)]

    document_id = PostgresStorage(conn).create_document("doc.pdf", "analyst")

    assert document_id == 7
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert statements[0] == _INSERT_DOCUMENT_IF_NEW
    assert statements[1] == _SELECT_DOCUMENT_ID
    assert statements[2] == _DELETE_DOCUMENT_CHUNKS
    assert "ON CONFLICT (name, access_role) DO NOTHING" in _INSERT_DOCUMENT_IF_NEW
    # Nothing updates the documents row: it is immutable once created.
    assert not any("UPDATE documents" in sql for sql in statements)


def test_insert_chunk_writes_one_row_tagged_and_numbered() -> None:
    conn, cursor = _mock_connection()
    chunk = _embedded(3, "gamma", [0.3, 0.4])

    PostgresStorage(conn).insert_chunk(7, "fixed", 1, chunk)

    # One chunk is written per call, keyed to the document, tagged with its
    # strategy and its 0-based index, with the embedding wrapped as a Vector.
    sql, row = cursor.execute.call_args.args
    assert sql == _INSERT_CHUNK
    assert row == (
        7,
        "fixed",
        1,
        3,
        chunk.page_char_count,
        chunk.page_word_count,
        chunk.page_sentence_count_raw,
        chunk.page_token_count,
        "gamma",
        Vector([0.3, 0.4]),
    )


def test_insert_chunk_is_wrapped_in_a_transaction() -> None:
    conn, _ = _mock_connection()

    PostgresStorage(conn).insert_chunk(7, "fixed", 0, Chunk.from_page(1, "x"))

    conn.transaction.assert_called_once_with()


def test_unembedded_chunk_is_stored_as_null() -> None:
    conn, cursor = _mock_connection()
    # A chunk that has not been embedded carries an empty embedding.
    PostgresStorage(conn).insert_chunk(
        7, "fixed", 0, Chunk.from_page(1, "not embedded")
    )

    _, row = cursor.execute.call_args.args
    assert row[9] is None


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


def test_delete_chunks_except_keeps_only_the_winner() -> None:
    conn, cursor = _mock_connection()
    cursor.rowcount = 4

    deleted = PostgresStorage(conn).delete_chunks_except(7, "semantic")

    assert deleted == 4
    cursor.execute.assert_called_once_with(_DELETE_LOSING_CHUNKS, (7, "semantic"))


def test_read_chunk_texts_by_strategy_groups_by_strategy_in_order() -> None:
    conn, cursor = _mock_connection()
    # Rows come back ordered by (strategy, chunk_index), as the SQL requests.
    cursor.fetchall.return_value = [
        ("fixed", "fixed chunk 0"),
        ("fixed", "fixed chunk 1"),
        ("semantic", "semantic chunk 0"),
    ]

    result = PostgresStorage(conn).read_chunk_texts_by_strategy(7, "analyst")

    # Filtered by document id and access role.
    cursor.execute.assert_called_once_with(_SELECT_CHUNK_TEXTS, (7, "analyst"))
    # Grouped per strategy, preserving chunk order within each.
    assert result == {
        "fixed": ["fixed chunk 0", "fixed chunk 1"],
        "semantic": ["semantic chunk 0"],
    }


def test_read_chunk_texts_by_strategy_empty_when_nothing_readable() -> None:
    conn, cursor = _mock_connection()
    cursor.fetchall.return_value = []

    assert PostgresStorage(conn).read_chunk_texts_by_strategy(7, "analyst") == {}


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

    # Autocommit is required so a read before a write doesn't leave a transaction
    # open that the write's transaction() block nests inside and never commits.
    connect_mock.assert_called_once_with("postgresql://localhost/test", autocommit=True)
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
        document_id = _store(storage, "integration-doc", "tester", {"fixed": [chunk]})

        with storage._conn.cursor() as cur:
            cur.execute(
                "SELECT name, access_role FROM documents WHERE id = %s",
                (document_id,),
            )
            assert cur.fetchone() == ("integration-doc", "tester")

            cur.execute(
                "SELECT chunk_index, text, embedding FROM chunks "
                "WHERE document_id = %s",
                (document_id,),
            )
            rows = cur.fetchall()
            assert len(rows) == 1
            index, text, embedding = rows[0]
            assert index == 0
            assert text == "integration text"
            assert len(embedding.to_list()) == 768

            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
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
        document_id = _store(
            storage,
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
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
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
        first = _store(
            storage,
            "dupe-doc",
            "dupe-tester",
            {"fixed": [_embedded(1, "first", vector)]},
        )
        second = _store(
            storage,
            "dupe-doc",
            "dupe-tester",
            {"semantic": [_embedded(1, "second pass", vector)]},
        )

        # Same row reused, and the old chunks replaced by the new ones.
        assert first == second
        with storage._conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM documents WHERE name = %s AND access_role = %s",
                ("dupe-doc", "dupe-tester"),
            )
            assert cur.fetchone() == (1,)
            cur.execute(
                "SELECT chunking_strategy, text FROM chunks WHERE document_id = %s",
                (second,),
            )
            assert cur.fetchall() == [("semantic", "second pass")]

            cur.execute("DELETE FROM documents WHERE id = %s", (second,))
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
        document_id = _store(
            storage,
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
        deleted = storage.delete_chunks_except(document_id, "semantic")
        assert deleted == 1
        remaining = storage.search_chunks(vector, "strategy-tester", top_k=10)
        assert [chunk.chunking_strategy for chunk in remaining] == ["semantic"]

        with storage._conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    finally:
        storage.close()


@pytest.mark.integration
def test_streamed_inserts_are_each_durable() -> None:
    """Each chunk inserted one at a time must persist independently.

    Mirrors how the service writes: create the document, then stream chunks with
    :meth:`insert_chunk`. Verifies via a *fresh* connection that every streamed
    chunk committed. Requires ``DATABASE_URL``; cleans up after itself.
    """
    conn_str = os.environ.get("DATABASE_URL")
    if not conn_str:
        pytest.skip("DATABASE_URL not set; skipping database integration test")

    vector = [1.0] + [0.0] * 767

    storage = PostgresStorage.connect(conn_str)
    try:
        document_id = storage.create_document("stream-doc", "stream-tester")
        # Stream three chunks across two strategies, one insert_chunk call each.
        storage.insert_chunk(document_id, "fixed", 0, _embedded(1, "fixed a", vector))
        storage.insert_chunk(document_id, "fixed", 1, _embedded(2, "fixed b", vector))
        storage.insert_chunk(
            document_id, "semantic", 0, _embedded(1, "semantic a", vector)
        )
    finally:
        storage.close()

    # A brand-new connection must see every streamed chunk: each has to commit.
    verifier = PostgresStorage.connect(conn_str)
    try:
        by_strategy = verifier.read_chunk_texts_by_strategy(
            document_id, "stream-tester"
        )
        assert by_strategy == {
            "fixed": ["fixed a", "fixed b"],
            "semantic": ["semantic a"],
        }

        with verifier._conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    finally:
        verifier.close()


@pytest.mark.integration
def test_read_then_delete_on_one_connection_persists() -> None:
    """A read before a write must not stop the write from committing.

    Reproduces the /evaluate flow: read the stored strategies back, then delete
    the losers — on the *same* connection. Under a non-autocommit connection the
    read opened an implicit transaction and the delete's ``transaction()`` block
    nested inside it as a savepoint that the connection close rolled back, so the
    delete silently vanished. Verifies the delete is durable via a *fresh*
    connection. Requires ``DATABASE_URL``; cleans up after itself.
    """
    conn_str = os.environ.get("DATABASE_URL")
    if not conn_str:
        pytest.skip("DATABASE_URL not set; skipping database integration test")

    vector = [1.0] + [0.0] * 767

    storage = PostgresStorage.connect(conn_str)
    try:
        document_id = _store(
            storage,
            "read-then-delete-doc",
            "rtd-tester",
            {
                "fixed": [_embedded(1, "fixed chunk", vector)],
                "semantic": [_embedded(1, "semantic chunk", vector)],
            },
        )

        # Read first (opens an implicit tx on a non-autocommit connection)...
        by_strategy = storage.read_chunk_texts_by_strategy(document_id, "rtd-tester")
        assert set(by_strategy) == {"fixed", "semantic"}
        # ...then delete the losers on the same connection.
        deleted = storage.delete_chunks_except(document_id, "fixed")
        assert deleted == 1
    finally:
        storage.close()

    # A brand-new connection must see the delete: it has to have committed.
    verifier = PostgresStorage.connect(conn_str)
    try:
        remaining = verifier.read_chunk_texts_by_strategy(document_id, "rtd-tester")
        assert set(remaining) == {"fixed"}

        with verifier._conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    finally:
        verifier.close()
