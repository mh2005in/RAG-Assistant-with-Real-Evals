# RAG Assistant with Real Evals - In Progress

A Retrieval-Augmented Generation (RAG) assistant built with a rigorous, evaluation-driven approach. This project explores the full RAG pipeline — from document ingestion through chunking, embedding, and retrieval — and measures each stage with real evaluations rather than vibes.

## Pipeline Overview

The system is organized into the following stages:

### 1. Document Extraction

Extract text, images, and structured data from source documents:

- **PyMuPDF** — text extraction
- **Tesseract OCR** — text and image extraction
- **Docling** — text, image, and tabular data extraction

### 2. Web Scraping

Collect content from the web:

- **Firecrawl**
- **Pyppeteer**
- **Beautiful Soup**

### 3. Chunking

Split extracted content into retrievable units. Strategies under evaluation:

- **Fixed** chunking
- **Semantic** chunking
- **Structural** chunking
- **Recursive** chunking
- **LLM-based** chunking

### 4. Embedding

Convert chunks into vector representations for similarity search via a local
**Ollama** embedding model (default `nomic-embed-text`, 768-dim, matching the
`vector(768)` storage column). The server and model come from `$OLLAMA_BASE_URL`
and `$OLLAMA_EMBED_MODEL`; the compose stack runs Ollama and pulls the model.
Embedders sit behind the `Embedder` interface
([`services/embedding/`](services/embedding/)) so backends stay swappable.

### 5. Storage

Persist embeddings and metadata for retrieval:

- **PostgreSQL** with the **pgvector** extension

Documents and their embedded chunks are stored in the `documents` and `chunks`
tables ([`db/schema.sql`](db/schema.sql)); `PostgresStorage`
([`services/storage/postgres.py`](services/storage/postgres.py)) writes them.

**Quickstart (local database):**

```bash
cp .env.example .env            # local-dev credentials (see .env.example)
docker compose up -d            # Postgres + pgvector (applies db/schema.sql) and Ollama (pulls the embedding + generation models)
```

The default connection string is `postgresql://rag:rag@localhost:5435/rag`
(host port `5435` → container `5432`). `PostgresStorage.connect()` reads it from
`$DATABASE_URL`. With the database up, the storage integration test runs instead
of skipping:

```bash
DATABASE_URL=postgresql://rag:rag@localhost:5435/rag uv run pytest -m integration
```

`db/schema.sql` is applied only when the data volume is first created; after
editing it, re-run with `docker compose down -v && docker compose up -d`.

With the database up, `POST /process` (multipart: `file`, `strategy`, `name`,
`access_role`, ...) chunks, embeds, and stores a document, and `POST /retrieve`
(JSON: `query`, `access_role`, `top_k`) runs a pgvector similarity search over
the stored chunks — filtered to the given `access_role` — returning the closest
chunks with cosine-similarity scores.

### 6. Augmented generation

Answer questions from the stored documents (the "AG" in RAG):

- **Ollama** serving a local LLM (default `gemma2:2b`)

`POST /answer` (JSON: `query`, `access_role`, `top_k`) retrieves the most
relevant chunks, builds a prompt that grounds the model in them (the *augment*
step), and returns the generated answer with its source chunks. The LLM backend
lives behind the `LLMClient` interface
([`services/generation/`](services/generation/)) and the server/model come from
`$OLLAMA_BASE_URL` and `$OLLAMA_MODEL`. The compose stack runs Ollama and pulls
the model; swap it via `OLLAMA_MODEL` (e.g. `llama3.2:3b`), then
`docker compose up -d ollama-pull`.

### 7. Validation

Validate structured inputs and outputs:

- **Pydantic** schema validation
- **LLM-based** validation

## Status

Early development — architecture and tooling are still being finalized.
