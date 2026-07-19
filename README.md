# RAG Assistant with Real Evals

A local-first **Retrieval-Augmented Generation (RAG)** service built with an
**evaluation-driven** approach: every pipeline stage is meant to be measured with
real evals, not vibes. Upload a document, and the app extracts, chunks, embeds,
and stores it; then ask questions and get answers grounded in — and cited from —
your own documents.

Everything runs **locally**: PostgreSQL + pgvector for storage, and
[Ollama](https://ollama.com) for both embeddings and generation. No external API
keys required.

> **Status:** early development. The full RAG loop (ingest → store → retrieve →
> answer) works end-to-end today; several stages have planned backends that are
> not built yet (see [Roadmap](#roadmap)).

## What it does today

```mermaid
flowchart LR
    subgraph ingest["POST /process"]
      direction TB
      U["PDF upload"] --> EX["Extract text<br/>(PyMuPDF)"]
      EX --> CH["Chunk<br/>(fixed-size, word-based)"]
      CH --> EM1["Embed<br/>(Ollama)"]
      EM1 --> ST[("PostgreSQL + pgvector<br/>documents, chunks")]
    end
    subgraph ask["POST /retrieve and /answer"]
      direction TB
      Q["Query"] --> EM2["Embed query<br/>(Ollama)"]
      EM2 --> SR["Similarity search<br/>(pgvector cosine + access_role)"]
      SR --> AUG["Augment prompt<br/>with retrieved chunks"]
      AUG --> GEN["Generate<br/>(Ollama)"]
      GEN --> A["Answer + sources"]
    end
    ST -.-> SR
```

- **`POST /process`** — detect + extract a PDF (PyMuPDF), chunk it, embed the
  chunks, and store them under a name and access role. Returns the stored
  document id and per-chunk stats.
- **`POST /retrieve`** — embed a query and run a pgvector cosine similarity
  search over the stored chunks, filtered by access role. Returns the closest
  chunks with similarity scores.
- **`POST /answer`** — retrieve context, build a prompt that grounds the model in
  it (the *augment* step), and generate a cited answer with its source chunks.

Each stage sits behind a small interface (`Chunker`, `Embedder`, `LLMClient`,
`PostgresStorage`) so strategies/backends stay swappable and comparable in evals.

## Tech stack

| Area | Choice |
| --- | --- |
| Language / runtime | Python 3.13 |
| Package / env manager | [`uv`](https://docs.astral.sh/uv/) |
| Web framework | FastAPI + Uvicorn |
| Validation | Pydantic v2 (all request/response DTOs) |
| PDF extraction | PyMuPDF |
| Embeddings & generation | Ollama (`nomic-embed-text` 768-dim, `gemma2:2b`) |
| Vector store | PostgreSQL 17 + pgvector (HNSW, cosine) |
| DB driver | psycopg 3 + pgvector adapter |
| Tests / types / lint | pytest, mypy, Ruff |
| Local stack | Docker Compose (app + db + Ollama) |

## Quickstart (Docker)

The whole stack — the app plus Postgres/pgvector and Ollama — runs from Docker
Compose. You only need Docker installed.

```bash
cp .env.example .env             # local-dev defaults (rag/rag); not production secrets
docker compose up -d --build     # builds the app image, starts db + ollama, pulls the models
```

On first start this pulls the Ollama models (`gemma2:2b` ~1.6 GB and
`nomic-embed-text` ~274 MB), so give it a few minutes. When it's up:

- App: <http://localhost:8000> — interactive API docs at
  <http://localhost:8000/docs>
- The app reaches its dependencies over the internal network (`db:5432`,
  `ollama:11434`); the published host ports (`5435`, `11434`) are only for direct
  access from your machine.

Stop it with `docker compose down` (add `-v` to also wipe the Postgres data and
pulled models).

## Using the API

**1. Process a document** (multipart form; `fixed_size` is a JSON string):

```bash
curl -X POST http://localhost:8000/process \
  -F "file=@mydoc.pdf;type=application/pdf" \
  -F "strategy=fixed" \
  -F "name=mydoc.pdf" \
  -F "access_role=analyst" \
  -F 'fixed_size={"chunk_size": 200}'
# -> { "processed": true, "doc_type": "pdf", "chunk_count": 12,
#      "document_id": 1, "chunks": [ ... ] }
```

`fixed_size` accepts `chunk_size` (number of **words** per chunk) and optional
`exclude_pages` (a mix of page numbers and inclusive ranges, e.g.
`[1, {"start": 10, "end": 12}]`).

**2. Retrieve relevant chunks:**

```bash
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "how are chunks embedded?", "access_role": "analyst", "top_k": 5}'
# -> { "query": "...", "count": 5, "results": [ {document_name, page_number, text, score}, ... ] }
```

**3. Ask a question** (retrieve + augmented generation):

```bash
curl -X POST http://localhost:8000/answer \
  -H "Content-Type: application/json" \
  -d '{"query": "how are chunks embedded?", "access_role": "analyst", "top_k": 5}'
# -> { "query": "...", "answer": "... [1]", "sources": [ ... ] }
```

**Access control:** a document is stored with a single `access_role`, and
`/retrieve` / `/answer` only search documents matching the request's role.

## Configuration

All configuration is via environment variables. In Docker Compose these are set
for you (the app's `DATABASE_URL` and `OLLAMA_BASE_URL` are built from the `db`
and `ollama` service configs); override defaults through `.env` or the shell. See
[`.env.example`](.env.example).

| Variable | Default | Used by |
| --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `rag` / `rag` / `rag` | Postgres container |
| `POSTGRES_PORT` | `5435` | host port for Postgres (container listens on 5432) |
| `APP_PORT` | `8000` | host port for the app |
| `OLLAMA_MODEL` | `gemma2:2b` | generation model (`/answer`) |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | embedding model (`/process`, `/retrieve`) |
| `OLLAMA_PORT` | `11434` | host port for Ollama |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | app → Ollama (compose sets `http://ollama:11434`) |
| `DATABASE_URL` | `postgresql://rag:rag@localhost:5435/rag` | app/tests **on the host**; the container builds its own (`db:5432`) |

To swap an Ollama model, change `OLLAMA_MODEL` / `OLLAMA_EMBED_MODEL` and re-run
`docker compose up -d ollama-pull`. A different embedding dimension would require
a schema change (the `chunks.embedding` column is `vector(768)`).

## Project layout

```
api.py                     FastAPI app: /process, /retrieve, /answer (+ DI wiring)
dtos/
  requests/                request models (chunking, retrieval, answer)
  responses/               response models (process, chunk, retrieval, answer, storage)
services/
  file_processing.py       /process: detect → extract → chunk → embed → store
  retrieval.py             /retrieve: embed query → similarity search
  answering.py             /answer: retrieve → augment prompt → generate
  chunking/                Chunker interface + fixed-size (word-based)
  embedding/               Embedder interface + Ollama backend
  generation/              LLMClient interface + Ollama backend
  storage/                 PostgresStorage (pgvector reads/writes)
db/schema.sql              documents + chunks tables, FK + HNSW cosine index
evals/                     reproducible evals (fixed-size chunking baseline)
tests/                     pytest: fast offline units + DB integration (marked)
docker-compose.yml         app + Postgres/pgvector + Ollama
Dockerfile                 app image (uv, uvicorn)
```

### Data model

- **`documents`** — `id`, `name`, `access_role`, `created_at`.
- **`chunks`** — `id`, `document_id` (FK, cascade delete), `chunk_index`,
  per-page stats, `text`, `embedding vector(768)`, `created_at`; with an HNSW
  cosine index for similarity search. See [`db/schema.sql`](db/schema.sql).

## Development

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.13. Dependencies live in
`pyproject.toml`; the lockfile is `uv.lock` (both are committed).

```bash
uv sync                          # install deps into .venv
uv run pytest                    # fast, offline unit tests
uv run ruff format . && uv run ruff check .
uv run mypy .
```

**Integration tests** need a live database and are skipped otherwise. With the
compose stack up:

```bash
DATABASE_URL=postgresql://rag:rag@localhost:5435/rag uv run pytest -m integration
```

**Evals** are reproducible and checked in as regenerable artifacts:

```bash
uv run python -m evals.fixed_size_chunking_eval   # writes evals/results/fixed_size_chunking.json
```

**Pre-commit hook:** a gitleaks secret scan runs on commit. Enable the repo's
hooks in a fresh clone with `git config core.hooksPath .githooks` (requires
[gitleaks](https://github.com/gitleaks/gitleaks#installing) installed). See
[CLAUDE.md](CLAUDE.md) for the full contributor conventions.

## Roadmap

Planned but **not yet implemented**:

- **More chunking strategies** — semantic, structural, recursive, and LLM-based,
  each behind the existing `Chunker` interface so they plug into the same
  pipeline as the fixed-size baseline.
- **Eval-driven strategy selection** — compare chunking strategies on the same
  data with real evals, surface the results, and let the user pick the strategy
  (or default to the best-measured one) rather than hardcoding fixed-size.
- **Richer document & role categorization** — finer-grained document categories
  and user roles, so retrieval and the augmented prompt are scoped precisely to
  each user for more relevant, on-target answers, instead of a single flat
  `access_role`.
- **Extraction:** OCR (Tesseract) and richer extraction (Docling); non-PDF types.
- **Web scraping:** Firecrawl / headless-browser / BeautifulSoup ingestion.
- **More evals:** embedding/retrieval quality (recall@k / MRR) and
  answer-faithfulness for generation.
- **Validation:** LLM-based output validation alongside the Pydantic schemas.
