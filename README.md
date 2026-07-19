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

Convert chunks into vector representations for similarity search via
**sentence-transformers**. The model (default `all-mpnet-base-v2`, 768-dim) and
the compute device (default `cpu`) are configurable. See the comparative
baseline in [`evals/results/embedding.json`](evals/results/embedding.json)
(regenerate with `uv run python -m evals.embedding_eval`).

### 5. Storage

Persist embeddings and metadata for retrieval:

- **PostgreSQL** with the **pgvector** extension

Documents and their embedded chunks are stored in the `documents` and `chunks`
tables ([`db/schema.sql`](db/schema.sql)); `PostgresStorage`
([`services/storage/postgres.py`](services/storage/postgres.py)) writes them.

**Quickstart (local database):**

```bash
cp .env.example .env            # local-dev credentials (see .env.example)
docker compose up -d            # Postgres + pgvector; applies db/schema.sql on first boot
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

### 6. Validation

Validate structured inputs and outputs:

- **Pydantic** schema validation
- **LLM-based** validation

## Status

Early development — architecture and tooling are still being finalized.
