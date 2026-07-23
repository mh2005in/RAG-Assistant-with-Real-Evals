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
      EX --> CH["Chunk every strategy<br/>(fixed-size, semantic)"]
      CH --> EM1["Embed<br/>(Ollama)"]
      EM1 --> SC["Score + keep the best<br/>(cohesion vs separation)"]
      SC --> ST[("PostgreSQL + pgvector<br/>documents, chunks")]
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

- **`POST /process`** — detect + extract a PDF (PyMuPDF), chunk it with **every**
  strategy, embed and store them all, score each one, and keep only the winner's
  chunks. You don't pick a strategy: the response reports every strategy's score
  and names the one that remains.
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

**1. Process a document** (multipart form):

```bash
curl -X POST http://localhost:8000/process \
  -F "file=@mydoc.pdf;type=application/pdf" \
  -F "name=mydoc.pdf" \
  -F "access_role=analyst" \
  -F "chunk_size=200" \
  -F 'exclude_pages=[1, {"start": 10, "end": 12}]'
# -> { "processed": true, "doc_type": "pdf", "document_id": 1,
#      "chunking_strategy": "semantic",          # the one that remains
#      "evaluations": [                          # best first
#        {"strategy": "semantic", "chunk_count": 12, "mean_chunk_words": 84.2,
#         "cohesion": 0.67, "separation": 0.49, "score": 0.18, "selected": true},
#        {"strategy": "fixed", ..., "score": 0.0, "selected": false}
#      ] }
```

**No `strategy` field.** Every implemented strategy chunks the document, all of
their chunks are stored against one `documents` row, each is scored, and the
losers' chunks are deleted — so exactly one strategy survives per document.
Re-processing the same document (same `name` + `access_role`) reuses that row and
replaces its chunks, so the table never accumulates duplicates.

The response reports the **evaluation only** — which strategy won and how each
scored — not the chunks themselves. Read the stored chunks back through
`/retrieve`.

How the winner is chosen — a label-free, silhouette-style score over sentence
embeddings:

- **cohesion** — mean similarity between sentences *inside* a chunk (higher is
  better: each chunk is about one thing).
- **separation** — mean similarity between *neighbouring* chunks (lower is
  better: boundaries fall where the content changes).
- **score = cohesion − separation**, highest wins. The two terms balance:
  over-splitting leaves neighbours nearly identical, under-splitting mixes topics
  inside a chunk. A single-chunk candidate scores **0.0** (no structure found),
  and a negative score means the split is worse than not splitting at all.

> This measures chunk *structure*, not answer quality. It needs no labels, so it
> runs on whatever you upload — but a retrieval eval against labelled queries is
> the stronger signal, and is on the [Roadmap](#roadmap).

The remaining inputs:

- **`chunk_size`** — optional positive integer, tuning only the **fixed-size**
  candidate (default 200 words). Other strategies choose their own boundaries.
- **`exclude_pages`** — optional and **strategy-agnostic**: a JSON **array** of
  page numbers and/or inclusive ranges, e.g. `[1, {"start": 10, "end": 12}]`.
  Applied to the extracted pages before any chunking, so it works the same for
  every strategy. Excluded pages don't shift the numbering of the pages that
  remain.

**2. Retrieve relevant chunks:**

```bash
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "how are chunks embedded?", "access_role": "analyst", "top_k": 5}'
# -> { "query": "...", "count": 5,
#      "results": [ {document_name, chunking_strategy, page_number, text, score}, ... ] }
```

Both `/retrieve` and `/answer` accept an optional `"chunking_strategy": "semantic"`
to search only the chunks produced by that strategy — which is how the same
document, chunked several ways, gets compared.

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
| `OLLAMA_GPU_COUNT` | `0` | GPUs given to Ollama: `0` = CPU, `all` = every NVIDIA GPU, `N` = N GPUs |
| `OLLAMA_PORT` | `11434` | host port for Ollama |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | app → Ollama (compose sets `http://ollama:11434`) |
| `DATABASE_URL` | `postgresql://rag:rag@localhost:5435/rag` | app/tests **on the host**; the container builds its own (`db:5432`) |

To swap an Ollama model, change `OLLAMA_MODEL` / `OLLAMA_EMBED_MODEL` and re-run
`docker compose up -d ollama-pull`. A different embedding dimension would require
a schema change (the `chunks.embedding` column is `vector(768)`).

### CPU or CUDA

Ollama runs both the embedding and the generation model, so it is the only
service doing tensor maths — the app itself has no GPU dependency. Switch it with
one variable and recreate the container:

```bash
OLLAMA_GPU_COUNT=all docker compose up -d ollama   # CUDA
OLLAMA_GPU_COUNT=0   docker compose up -d ollama   # CPU (default, works everywhere)
```

Anything other than `0` needs the [NVIDIA Container
Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
on the host. Confirm which one is in use with `docker exec rag-ollama ollama ps`
and read the `PROCESSOR` column.

**GPU is not automatically a win on a small card.** The models must fit in VRAM
together or Ollama reloads them on every switch. Measured on a 4 GB GTX 1650 with
the defaults (`gemma2:2b` + `nomic-embed-text`, which together exceed 4 GB):

| | generation | embedding (8 texts, warm) |
| --- | --- | --- |
| CPU | 10.9 tok/s | ~112 ms compute |
| CUDA | **17.1 tok/s** | ~201 ms compute + **~1.3 s reload** |

Generation gets ~1.6x faster, but embedding gets *slower* because the two models
thrash VRAM. On a card that fits both (≥8 GB), or with a smaller generation model
such as `llama3.2:1b`, both stages benefit.

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
  chunking/                Chunker interface + fixed-size and semantic strategies
  embedding/               Embedder interface + Ollama backend
  generation/              LLMClient interface + Ollama backend
  storage/                 PostgresStorage (pgvector reads/writes)
db/schema.sql              documents + chunks tables, FK + HNSW cosine index
evals/                     reproducible evals (chunking strategy comparison)
tests/                     pytest: fast offline units + DB integration (marked)
docker-compose.yml         app + Postgres/pgvector + Ollama
Dockerfile                 app image (uv, uvicorn)
```

### Data model

- **`documents`** — `id`, `name`, `access_role`, `created_at`, unique on
  `(name, access_role)`. One row per document: processing the same document again
  reuses its row and replaces its chunks, rather than adding a duplicate — the
  chunks already record which strategy produced them.
- **`chunks`** — `id`, `document_id` (FK, cascade delete), `chunking_strategy`,
  `chunk_index`, per-page stats, `text`, `embedding vector(768)`, `created_at`;
  with an HNSW cosine index for similarity search. See
  [`db/schema.sql`](db/schema.sql).

  `chunking_strategy` records which strategy produced each chunk. During
  `/process` every strategy's chunks are written against the same `documents`
  row (numbered from 0 *per strategy*), scored, and then all but the winner are
  deleted — so a stored document ends up holding exactly one strategy's chunks.
  `/retrieve` and `/answer` can still filter by it.

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

**Evals** are reproducible and checked in as regenerable artifacts. The strategy
comparison embeds sentences, so it needs the Ollama service running:

```bash
uv run python -m evals.fixed_size_chunking_eval    # fixed-size baseline sweep
uv run python -m evals.chunking_strategies_eval   # fixed vs semantic, same document
```

**Pre-commit hook:** a gitleaks secret scan runs on commit. Enable the repo's
hooks in a fresh clone with `git config core.hooksPath .githooks` (requires
[gitleaks](https://github.com/gitleaks/gitleaks#installing) installed). See
[CLAUDE.md](CLAUDE.md) for the full contributor conventions.

## Roadmap

Planned but **not yet implemented**:

- **More chunking strategies** — structural, recursive, and LLM-based, each
  behind the existing `Chunker` interface so they plug into the same pipeline as
  the fixed-size and semantic strategies.
- **Retrieval-quality strategy selection** — `/process` already compares every
  strategy and keeps the best by a label-free coherence score; the stronger
  signal is recall@k / MRR against labelled queries, which would replace (or
  outrank) the structural score when a labelled set exists.
- **Richer document & role categorization** — finer-grained document categories
  and user roles, so retrieval and the augmented prompt are scoped precisely to
  each user for more relevant, on-target answers, instead of a single flat
  `access_role`.
- **Extraction:** OCR (Tesseract) and richer extraction (Docling); non-PDF types.
- **Web scraping:** Firecrawl / headless-browser / BeautifulSoup ingestion.
- **More evals:** embedding/retrieval quality (recall@k / MRR) and
  answer-faithfulness for generation.
- **Validation:** LLM-based output validation alongside the Pydantic schemas.
