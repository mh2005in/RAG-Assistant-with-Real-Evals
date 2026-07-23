-- Storage schema (storage stage): documents and their embedded chunks.
--
-- Run against a fresh PostgreSQL database that has the pgvector extension
-- available. Connection details come from config/env, never hardcoded (see
-- CLAUDE.md) -- this file is DDL only.
--
--     psql "$DATABASE_URL" -f db/schema.sql

-- pgvector provides the ``vector`` column type and similarity operators.
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per source document. ``access_role`` is the single role permitted to
-- read the document and its chunks; role-based access is enforced in the
-- application layer by filtering on it. (If a document ever needs to be visible
-- to several roles, replace this column with a document_roles join table.)
CREATE TABLE documents (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT        NOT NULL,
    access_role TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One row per document. Re-processing the same document reuses this row and
    -- replaces its chunks, rather than piling up duplicates: the chunks already
    -- carry the strategy that produced them, so nothing needs a second row.
    UNIQUE (name, access_role)
);

-- One row per chunk produced from a document. Columns mirror the ``Chunk``
-- response DTO (dtos/responses/chunk.py); ``chunk_index`` preserves the order
-- chunks were produced in so a document can be reconstructed / cited in order.
--
-- ``embedding`` is vector(768) to match the default embedding model
-- (Ollama's nomic-embed-text, 768-dim). pgvector columns are fixed-dimension, so
-- this is coupled to the model: a different-dimension model (e.g. a 1024-dim
-- model) would need a different column or table.
CREATE TABLE chunks (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id             BIGINT      NOT NULL
                                REFERENCES documents (id) ON DELETE CASCADE,
    -- Which chunking strategy produced this chunk. The same document can be
    -- chunked several ways so the strategies can be compared on equal footing;
    -- retrieval can then be filtered to one strategy, and the losers deleted
    -- (DELETE FROM chunks WHERE chunking_strategy <> '<winner>') without
    -- touching the documents rows. Values come from the app's ChunkingStrategy
    -- enum, which is the source of truth.
    chunking_strategy       TEXT        NOT NULL,
    chunk_index             INT         NOT NULL,
    page_number             INT         NOT NULL,
    page_char_count         INT         NOT NULL,
    page_word_count         INT         NOT NULL,
    page_sentence_count_raw INT         NOT NULL,
    page_token_count        REAL        NOT NULL,
    text                    TEXT        NOT NULL,
    embedding               vector(768),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Chunks are numbered 0, 1, 2, ... within a document *for a given strategy*,
    -- so the same document can hold several strategies' chunks side by side.
    UNIQUE (document_id, chunking_strategy, chunk_index)
);

-- Fetch/delete a document's chunks by foreign key.
CREATE INDEX chunks_document_id_idx ON chunks (document_id);

-- Filter retrieval to one strategy, and delete the losing strategies in bulk.
CREATE INDEX chunks_chunking_strategy_idx ON chunks (chunking_strategy);

-- Approximate-nearest-neighbour index for similarity search. Cosine distance is
-- the usual metric for these embeddings and matches how retrieval ranks chunks.
-- HNSW requires pgvector >= 0.5.0.
CREATE INDEX chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
