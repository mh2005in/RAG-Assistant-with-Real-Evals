# RAG Assistant with Real Evals

A local-first **Retrieval-Augmented Generation (RAG)** service built with an
**evaluation-driven** approach: every pipeline stage is measured by a real,
checked-in eval, not vibes. Upload a document, and the app extracts, chunks, embeds,
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
      U["Upload<br/>PDF · DOCX · HTML · text"] --> EX["Extract text<br/>(per-format extractor)"]
      EX --> CH["Chunk every strategy<br/>(fixed-size, semantic, structural)"]
      CH --> EM1["Embed<br/>(Ollama)"]
      EM1 --> ST[("PostgreSQL + pgvector<br/>documents, chunks")]
    end
    subgraph eval["POST /evaluate"]
      direction TB
      QA["Q&amp;A pairs"] --> RS["Retrieve per strategy<br/>(pgvector) + match answers"]
      RS --> PR["Keep the best,<br/>delete the rest"]
    end
    subgraph ask["POST /retrieve and /answer"]
      direction TB
      Q["Query"] --> EM2["Embed query<br/>(Ollama)"]
      EM2 --> SR["Similarity search<br/>(pgvector cosine + access_role)"]
      SR --> AUG["Augment prompt<br/>with retrieved chunks"]
      AUG --> GEN["Generate<br/>(Ollama)"]
      GEN --> A["Answer + sources"]
    end
    ST -.-> RD
    PR -.-> ST
    ST -.-> SR
```

- **`POST /process`** — detect the document type, extract its text, chunk it with
  **every** strategy, and embed and store them all. Four types are ingested — PDF
  (PyMuPDF), DOCX (python-docx), HTML (BeautifulSoup) and plain text — each behind
  the same `Extractor` interface; anything else comes back as `doc_type:
  "unknown"` and is stored as nothing. You don't pick a strategy, and none is
  scored or dropped here: the response reports which strategies were stored and
  their chunk counts.
- **`POST /evaluate`** — score a stored document's strategies against a caller-
  supplied labelled set (question/expected-answer pairs): retrieve against each
  strategy for every question, rank the strategies by how well their retrievals
  match the expected answers (aggregated with pandas), then keep the winner's
  chunks and delete the losers. Scoring is a **separate stage** from chunking, so
  a document can be re-evaluated (e.g. with a different question set) without
  re-processing.
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
| Document extraction | PyMuPDF (PDF), python-docx (DOCX), BeautifulSoup (HTML) |
| Embeddings & generation | Ollama (`nomic-embed-text` 768-dim, `gemma2:2b`) |
| Vector store | PostgreSQL 17 + pgvector (HNSW, cosine) |
| DB driver | psycopg 3 + pgvector adapter |
| Eval scoring | pandas (+ NumPy) for the `/evaluate` retrieval eval |
| Tests / types / lint | pytest, mypy, Ruff |
| CI | GitHub Actions (backend gates; mocked frontend E2E) |
| Local stack | Docker Compose (app + db + Ollama) |

## Quickstart (Docker)

The whole stack — the Angular frontend, the app, Postgres/pgvector and Ollama —
runs from Docker Compose. You only need Docker installed.

```bash
cp .env.example .env             # local-dev defaults (rag/rag); not production secrets
docker compose up -d --build     # builds the frontend + app images, starts db + ollama, pulls the models
```

On first start this pulls the Ollama models (`gemma2:2b` ~1.6 GB and
`nomic-embed-text` ~274 MB), so give it a moment on the first run. `gemma2:2b`
runs comfortably on modest hardware (CPU-only is fine). For higher-quality answers
on a bigger machine, set `OLLAMA_MODEL=gpt-oss:20b` (~13 GB, needs ~16 GB of
RAM/VRAM) in `.env`. When it's up:

- Frontend: <http://localhost:4200> — the web UI (Ask + Admin tabs). It proxies
  API calls to the app internally, so everything is same-origin.
- App: <http://localhost:8000> — interactive API docs at
  <http://localhost:8000/docs>
- Services reach each other over the internal network (the frontend proxies to
  `app:8000`; the app talks to `db:5432` and `ollama:11434`); the published host
  ports (`4200`, `8000`, `5435`, `11434`) are only for direct access from your
  machine.

Stop it with `docker compose down` (add `-v` to also wipe the Postgres data and
pulled models).

The Compose project name is pinned in
[`docker-compose.yml`](docker-compose.yml), so **every checkout of this
repository — the root one and any git worktree — is the same stack**. Bringing it
up from a worktree adopts the containers and volumes that are already there
instead of starting a second copy that fights the first over the `rag-*` container
names and the published ports, and `docker compose down` from any checkout stops
it. The trade-off is that two checkouts cannot run the stack simultaneously; they
never could, since they share the host ports.

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
#      "strategies": [                           # what was stored, unscored
#        {"strategy": "fixed", "chunk_count": 18},
#        {"strategy": "semantic", "chunk_count": 12},
#        {"strategy": "structural", "chunk_count": 15}
#      ] }
```

**Four document types.** PDF, DOCX, HTML and plain text are all accepted on the
same endpoint, and the detected type comes back in `doc_type`. The type is
sniffed from the bytes first (the `%PDF-` marker, the `word/document.xml` entry
inside the Office ZIP, HTML's own tags), so a mislabelled file is still classified
by what it actually is; the declared content type is consulted next and the
filename extension last. Plain text is the one format with no signature of its
own, so it needs one of those two hints:

```bash
curl -X POST http://localhost:8000/process \
  -F "file=@handbook.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -F "name=handbook.docx" \
  -F "access_role=analyst"
# -> { "processed": true, "doc_type": "docx", "document_id": 2, "strategies": [...] }
```

A file whose type cannot be identified comes back as `doc_type: "unknown"` with
`processed: true`, no `document_id` and no strategies — it is reported, not
ingested, so a stray binary never reaches the embeddings.

**Only PDFs have pages.** DOCX, HTML and plain text leave pagination to whatever
renders them, so they extract to a single page: their chunks all cite page 1 and
the per-page stats describe the whole document. `exclude_pages` still applies —
excluding page 1 of a paginationless document excludes the document.

**No `strategy` field.** Every implemented strategy chunks the document and all of
their chunks are stored against one `documents` row — none is scored or dropped
here. Re-processing the same document (same `name` + `access_role`) reuses that
row and replaces its chunks, so the table never accumulates duplicates.

The response reports **what was stored** — the strategies and their chunk counts —
not the chunks themselves. Read the stored chunks back through `/retrieve`, and
compare the strategies with `/evaluate`.

The strategies that run:

- **fixed-size** — windows of `chunk_size` words, ignoring every boundary. The
  structure-blind baseline the others have to beat.
- **semantic** — embeds each sentence and breaks where consecutive sentences drift
  apart in meaning, so boundaries land on topic shifts that nothing marks up.
- **structural** — breaks on the markers a document already carries, matched by
  regex over line starts: markdown headings, numbered sections (`1.`, `3.2.1`),
  `Chapter`/`Section`/`Appendix` labels, roman/lettered items and ALL-CAPS title
  lines. Needs no embeddings. A document with no markers at all falls back to
  paragraph boundaries, and sections are bounded either side: a very short one
  (a bare heading) merges into the next, an over-long one splits at paragraph,
  then sentence, then word boundaries.

The remaining inputs:

- **`chunk_size`** — optional positive integer, tuning only the **fixed-size**
  candidate (default 200 words). Other strategies choose their own boundaries.
- **`structural`** — optional JSON **object** tuning only the **structural**
  candidate: `heading_patterns` (regexes replacing the built-in markers),
  `min_words` (default 25) and `max_words` (default 400), e.g.
  `-F 'structural={"heading_patterns": ["^Clause \\d+"], "max_words": 300}'`. A
  pattern that does not compile is a 422.
- **`exclude_pages`** — optional and **strategy-agnostic**: a JSON **array** of
  page numbers and/or inclusive ranges, e.g. `[1, {"start": 10, "end": 12}]`.
  Applied to the extracted pages before any chunking, so it works the same for
  every strategy. Excluded pages don't shift the numbering of the pages that
  remain.

**2. Evaluate the stored strategies against your Q&A and keep the best:**

```bash
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{
        "document_id": 1,
        "access_role": "analyst",
        "top_k": 5,
        "qa_pairs": [
          {"question": "how are chunks embedded?", "answer": "with Ollama nomic-embed-text"},
          {"question": "what is the vector store?", "answer": "PostgreSQL with pgvector"}
        ]
      }'
# -> { "document_id": 1,
#      "chunking_strategy": "semantic",          # the one that remains
#      "evaluations": [                          # best first
#        {"strategy": "semantic", "questions": 2,
#         "answer_similarity": 0.81, "hit_rate": 1.0,
#         "recall_at_k": 0.75, "mrr": 1.0, "ndcg_at_k": 0.92, "selected": true},
#        {"strategy": "fixed", "questions": 2,
#         "answer_similarity": 0.63, "hit_rate": 0.5,
#         "recall_at_k": 0.5, "mrr": 0.5, "ndcg_at_k": 0.63, "selected": false}
#      ] }
```

Scoring is a **separate stage** from chunking: `/process` never judges the
strategies it stores, so chunking stays cheap and a document can be re-evaluated
(e.g. with a different question set) without re-chunking. `/evaluate` decides the
winner by **how well each strategy actually retrieves** — keeping the winner's
chunks and **deleting the rest**, so the document ends up holding exactly one
strategy. Only a document matching the request's `access_role` is evaluated (a 404
means no readable chunks).

How the winner is chosen — a labelled retrieval eval driven by your `qa_pairs`:

- For each **question**, retrieve the top-`top_k` chunks **per strategy** (the same
  pgvector cosine search `/retrieve` uses, confined to this document and strategy).
- Compare those retrieved chunks to the question's **expected answer** by cosine
  similarity; each question's score is the best match found.
- **`answer_similarity`** is the mean of those best matches across all questions —
  the ranking metric; the highest wins. **`hit_rate`** is the fraction of questions
  whose answer was matched above a similarity threshold. The per-question scores are
  aggregated per strategy with **pandas**.

Those two say how *close* the best chunk came. They say nothing about **where in
the ranking** it landed — surfacing the answer at position 1 and at position 5
score the same. Three standard rank-aware metrics are reported alongside them
(`services/rank_metrics.py`), using the same relevance threshold as `hit_rate`, so
"relevant" means one thing throughout:

- **`recall_at_k`** — of all the chunks that could have answered the question, the
  share that reached the top `top_k`. The denominator is the **whole document**, not
  just what was retrieved, so a strategy holding more relevant chunks than `top_k`
  has room for scores below 1.0 however well it ranks.
- **`mrr`** — mean reciprocal rank: `1/position` of the first relevant chunk, so
  position 1 scores 1.0 and position 4 scores 0.25. How fast a reader reaches
  something useful.
- **`ndcg_at_k`** — rewards ranking *every* relevant chunk early, not just the first,
  normalised against the best ordering that retrieval could have had.

`recall_at_k` and `ndcg_at_k` are **`null`** when no chunk in the document matches a
question's expected answer at all — undefined rather than zero, since a retriever
cannot miss what is not there. A `null` next to a `hit_rate` of 0 usually means the
question set does not match the document.

> **These are reported, not used to pick the winner.** `answer_similarity` alone
> still selects the strategy that is kept, so the numbers are a measurement of the
> current behaviour rather than a change to it.

> This measures **retrieval quality on your labelled questions** — the strategy that
> best surfaces the answers you care about. Give it questions whose answers live in
> the document; more/representative pairs make the ranking more reliable.

**Why embedding similarity and not an LLM judge?** The `qa_pairs` are authored
**ahead of time, outside this system** (typically generated by an LLM offline),
so the eval itself does no LLM calls — it scores answers with the same local,
open-source embedding model used everywhere else (Ollama `nomic-embed-text`).
That keeps the running pipeline **fully open-source and free of per-call LLM
cost**: the one-off LLM spend to write the question set happens externally, and
`/evaluate` stays a cheap, repeatable, offline scorer.

**3. Retrieve relevant chunks:**

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

**4. Ask a question** (retrieve + augmented generation):

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

**GPU only helps if the model fits in VRAM.** Ollama offloads as many layers as
fit and runs the rest on CPU. The default `gemma2:2b` (~1.6 GB) fits even on a
small card (e.g. a 4 GB GTX 1650) and is meaningfully faster on CUDA there. A big
model like `gpt-oss:20b` (~16 GB) barely offloads on such a card and runs on CPU
either way, so `OLLAMA_GPU_COUNT=all` makes little difference until it fits.
Check what actually happened with `docker exec rag-ollama ollama ps` and
read the `PROCESSOR` column (`100% CPU`, `NN%/MM% CPU/GPU`, or `100% GPU`).

## Project layout

The repo is split into `backend/` (the Python/RAG service) and `frontend/`
(an Angular web UI — see [Frontend](#frontend-angular)). Docker Compose and the
shared environment config stay at the root and orchestrate both.

```
backend/                   the Python/RAG service (run uv commands from here)
  api.py                   FastAPI app: /process, /evaluate, /retrieve, /answer (+ DI wiring)
  dtos/
    requests/              request models (chunking, evaluate, retrieval, answer)
    responses/             response models (process, evaluate, chunk, retrieval, answer)
  services/
    file_processing.py     /process: detect → extract → chunk → embed → store
    evaluation.py          /evaluate: retrieve per strategy vs Q&A → rank → keep the best
    rank_metrics.py        recall@k / MRR / nDCG@k over a ranked retrieval (pure math)
    retrieval.py           /retrieve: embed query → similarity search
    answering.py           /answer: retrieve → augment prompt → generate
    chunking/              Chunker interface + fixed-size, semantic, structural
    embedding/             Embedder interface + Ollama backend
    extraction/            Extractor interface + pdf, docx, html, text
    generation/            LLMClient interface + Ollama backend + answer-faithfulness metric
    storage/               PostgresStorage (pgvector reads/writes)
  db/schema.sql            documents + chunks tables, FK + HNSW cosine index
  evals/                   reproducible evals — one per pipeline stage (+ data/, results/)
  tests/                   pytest: fast offline units + DB integration (marked)
  Dockerfile               app image (uv, uvicorn)
  pyproject.toml, uv.lock  dependencies + pinned lockfile
frontend/                  Angular web UI (standalone components, Angular 20)
  src/app/
    core/                  API client, DTO types, shared session (access role)
    user/                  Ask tab — /retrieve and /answer
    admin/                 Admin tab — upload (/process) and /evaluate
  proxy.conf.json          dev-server proxy: /process,/evaluate,/retrieve,/answer → :8000
  Dockerfile               builds the SPA, serves it with nginx (+ API reverse-proxy)
  nginx.conf               SPA fallback + proxies the API paths to app:8000
docker-compose.yml         frontend + app + Postgres/pgvector + Ollama
.env.example               shared environment config (Postgres, Ollama, ports)
.github/workflows/         CI: backend lint/types/fast tests, mocked frontend E2E
```

### Data model

- **`documents`** — `id`, `name`, `access_role`, `created_at`, unique on
  `(name, access_role)`. One row per document: processing the same document again
  reuses its row and replaces its chunks, rather than adding a duplicate — the
  chunks already record which strategy produced them.
- **`chunks`** — `id`, `document_id` (FK, cascade delete), `chunking_strategy`,
  `chunk_index`, per-page stats, `text`, `embedding vector(768)`, `created_at`;
  with an HNSW cosine index for similarity search. See
  [`backend/db/schema.sql`](backend/db/schema.sql).

  `chunking_strategy` records which strategy produced each chunk. During
  `/process` every strategy's chunks are written against the same `documents`
  row (numbered from 0 *per strategy*) and all are kept; `/evaluate` later scores
  them and deletes all but the winner — so an evaluated document ends up holding
  exactly one strategy's chunks. `/retrieve` and `/answer` can filter by it, and
  before evaluation it distinguishes the strategies stored side by side.

## Development

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.13. The Python project
lives in `backend/`, so run these from that directory (`cd backend`).
Dependencies live in `backend/pyproject.toml`; the lockfile is `backend/uv.lock`
(both are committed).

```bash
cd backend
uv sync                          # install deps into .venv
uv run pytest                    # fast, offline unit tests
uv run ruff format . && uv run ruff check .
uv run mypy .
```

**Integration tests** need a live database and are skipped otherwise. With the
compose stack up (run from `backend/`):

```bash
DATABASE_URL=postgresql://rag:rag@localhost:5435/rag uv run pytest -m integration
```

**Evals** are reproducible and checked in as regenerable artifacts, and **every
pipeline stage has one**. Five of them (both extraction evals, embedding, storage,
generation) carry a control arm — an arrangement that must score badly — because a
metric that cannot fail is not measuring anything; the chunking and retrieval
evals predate that convention and compare real candidates only. Run from
`backend/`:

```bash
uv run python -m evals.extraction_fidelity_eval    # does the text survive the PDF?
uv run python -m evals.extraction_formats_eval     # does it survive DOCX/HTML/text too?
uv run python -m evals.fixed_size_chunking_eval    # fixed-size baseline sweep
uv run python -m evals.chunking_strategies_eval    # fixed vs semantic vs structural
uv run python -m evals.embedding_quality_eval      # does "close" mean "means the same"?
uv run python -m evals.storage_index_eval          # how approximate is the HNSW index?
uv run python -m evals.retrieval_ranking_eval      # rank-aware retrieval metrics per strategy
uv run python -m evals.answer_faithfulness_eval    # is a generated answer grounded?
```

Most of them embed text, so they need the Ollama service running. Three are
different: the two extraction evals need neither Ollama nor a database, and the
storage eval needs **both** Ollama and a live PostgreSQL/pgvector — it is measuring the
index, which no in-memory stand-in can imitate. Give it the database the same way
the integration tests get it:

```bash
DATABASE_URL=postgresql://rag:rag@localhost:5435/rag uv run python -m evals.storage_index_eval
```

### Extraction fidelity: does the text survive the PDF?

Every other eval starts from a `.txt` fixture, which skips the stage that turns a
binary PDF into text. `evals/extraction_fidelity_eval.py` does not: it lays the
same two sample documents out into a PDF with PyMuPDF at run time — source
documents are never committed, so the eval makes its own — keeps the words it laid
out as ground truth, and then extracts them back five different ways. Two layouts,
because they stress different things: one column, and two columns where reading
order becomes a choice rather than a given.

| arm | one column | two columns |
| --- | --- | --- |
| **shipped** (`get_text()`) | **1.000** | **1.000** |
| `blocks`, `words` | 1.000 | 1.000 |
| `sorted` (`sort=True`) | 1.000 | **0.550 / 0.592** |
| `shuffled` *(control)* | 0.092 | 0.104 / 0.082 |

*(order fidelity, `sample.txt` / `structured_sample.txt`. Recall and precision are
1.000 for every arm on every layout, including the control.)*

Three things come out of it:

- **The shipped extractor is lossless here** — recall, precision, order and
  per-page attribution all 1.000, on both layouts. That is now measured rather
  than assumed.
- **The obvious "improvement" is a regression.** `get_text("text", sort=True)`
  sounds like the tidier option and reads a two-column page straight across,
  interleaving the columns: order fidelity falls to `0.55`–`0.59` while **not
  losing a single word**. Recall alone would have called it perfect.
- **The control earns the other numbers.** `shuffled` keeps every word and destroys
  only the order, and scores 1.000 recall against ~0.09 order fidelity — which is
  what says the two metrics are measuring different things.

The eval also runs page exclusion (`REQ-EXT-02`) through the same round trip: with
page 2 excluded, three pages still come back, the surviving pages keep all their
words (`kept_recall` 1.000) and no word unique to the excluded page leaks through
(`leaked_words` 0). The unit tests prove that over a list of strings; this proves
it over text that has actually been through a PDF — and it caught a real bug while
being written, when the eval passed the wrong field name to `PageExclusion` and
excluded nothing at all.

### Extraction formats: does the text survive the container?

`evals/extraction_formats_eval.py` asks the question ingestion breadth raises: a
new source is only worth having if the text that reaches the chunker is the same
text. The same paragraphs are written into all four containers at run time — again,
no source document is committed — and read back through the shipped seam, so the
only thing that differs between arms is the file format. PDF is the baseline,
because it is the path the rest of the pipeline was measured on.

| arm | pages | recall | precision | order fidelity |
| --- | --- | --- | --- | --- |
| `pdf` (baseline) | 3 | 1.000 | 1.000 | 1.000 |
| `docx` | 1 | 1.000 | 1.000 | 1.000 |
| `html` | 1 | 1.000 | 1.000 | 1.000 |
| `text` | 1 | 1.000 | 1.000 | 1.000 |
| `html_undressed` *(control)* | 1 | 0.971 | 0.844 | 0.903 |
| `text_shuffled` *(control)* | 1 | 1.000 | 1.000 | 0.059 |

*(`sample.txt`; `structured_sample.txt` gives the same four perfect candidate rows,
with the controls at 0.859 precision and 0.054 order fidelity.)*

**No container loses a word.** All four candidates recover every word, in order,
with nothing spurious added — so DOCX, HTML and plain text reach the chunker with
exactly what the PDF path delivers.

**The controls show the metrics can fail.** `html_undressed` reads the same HTML
bytes as plain text with the markup left in: the prose survives (recall holds) and
the tags, CSS and JavaScript ride along to cost it precision — which is what says
precision is measuring the markup handling rather than the text. `text_shuffled`
keeps every word and destroys only the order, and order fidelity collapses to
0.059 while recall stays at 1.000.

**Pagination is reported, not scored.** Only a PDF stores page boundaries; the
other three leave pagination to whatever renders them, so they extract to one page
and their per-page stats describe the whole document. That collapse is the
graceful degradation `REQ-EXT-04` asks for, so `pages_extracted` records it
instead of penalising it — scoring per page would punish three formats for a page
structure their sources never had.

**It turned up something.** On flat prose the *non-PDF* formats chunk better
structurally than the baseline: DOCX, HTML and text each yield 4 structural chunks
where the PDF yields 1. A PDF round trip has no blank lines left in it — PyMuPDF
returns one newline per laid-out line, so the paragraph breaks are gone and the
structural strategy's paragraph fallback has nothing to split on. Where a document
marks its own structure (`structured_sample.txt`), the headings survive the round
trip and all four formats agree at 11 chunks. The fixed-size strategy, which does
not read structure, is unaffected either way.

### Chunking strategies: where should the cuts go?

The comparison runs every strategy over two documents — flat prose
(`evals/data/sample.txt`) and one that marks up its own structure
(`evals/data/structured_sample.txt`) — and reports, next to the size
distribution, the label-free cohesion/separation score from
`services/chunking/coherence.py` (higher is better). On the structured document
the structural strategy scores best (`-0.18` vs `-0.31` semantic and `-0.31` to
`-0.38` fixed-size): it is both the most internally coherent and the most
distinct from its neighbours. On the flat document it has no markers to find,
falls back to paragraphs and lands with the rest (`-0.21`, against `-0.20`
semantic) — a structure-aware strategy is only as good as the structure it is
given.

### Embedding quality: does "close" mean "means the same"?

The embedder is the coordinate system every other number is computed in, so when
it is wrong they are all quietly wrong together. `evals/embedding_quality_eval.py`
measures it directly with 16 hand-written triplets: an anchor, a **paraphrase**
worded to share almost no vocabulary with it, and two things that should sit
further away — a **hard negative** that borrows the anchor's vocabulary but not its
meaning, and an **easy negative** from another subject entirely.

| arm | paraphrase cos | hard-negative accuracy | easy-negative accuracy |
| --- | --- | --- | --- |
| **`nomic-embed-text`** (shipped) | 0.604 | **0.000** | **0.812** |
| `nomic-embed-text` + task prefixes | 0.658 | 0.000 | 0.750 |
| `lexical-tfidf` *(baseline)* | 0.069 | 0.000 | 0.500 |
| `random` *(control)* | −0.003 | 0.625 | 0.500 |

*(16 triplets pooled over both documents. Accuracy is the share where the
paraphrase is closer to the anchor than the negative; the control's 0.625 is ten
coin flips out of sixteen, i.e. chance.)*

**The shipped embedder knows what text is about and not what it says.** It beats
chance comfortably on easy negatives (0.812) and **never once** — 0 of 16 — ranks a
paraphrase above a same-vocabulary contradiction. Nor does anything else tested:
TF-IDF scores 0/16 too, and by a wider margin (−0.539 against −0.286), so the
learned embedder is *less* wrong, not right. Splitting the hard negatives by how
they were written puts the same point another way: on outright **inversions**
("...sit close together" vs "...sit far apart") the margin is −0.333, and on
**adjacent facts** from the same document −0.145.

This is a caveat on everything downstream that treats cosine as meaning, the
faithfulness metric included — and it is why that metric scores claims against
context *sentences* rather than whole chunks, which is the best available
mitigation and not a fix.

**The two hard-coded thresholds are only meaningful against the similarity floor.**
The eval also scores every pair of corpus sentences, so `ANSWER_MATCH_THRESHOLD`
(0.6) and `SUPPORT_THRESHOLD` (0.75) can be read against what arbitrary text
already scores:

| arm | mean | p90 | share ≥ 0.6 | share ≥ 0.75 |
| --- | --- | --- | --- | --- |
| **`nomic-embed-text`** | 0.533 | 0.637 | **0.209** | 0.012 |
| + task prefixes | 0.664 | 0.738 | **0.851** | 0.069 |

- **`SUPPORT_THRESHOLD` is doing real work** — only 1.2% of arbitrary sentence
  pairs clear 0.75, which agrees with the independent sweep in the faithfulness
  eval.
- **`ANSWER_MATCH_THRESHOLD` is closer to the noise than it looks.** One arbitrary
  sentence pair in five already clears 0.6, and the 90th percentile of arbitrary
  pairs (0.637) sits *above* the mean cosine of a genuine paraphrase (0.604).
- **Adopting the model's documented task prefixes would break both thresholds.**
  `nomic-embed-text` is trained with `search_query:` / `search_document:` prefixes
  that the shipped code does not send. Adding them lifts paraphrase similarity
  (0.604 → 0.658) but lifts *everything* more: 85% of arbitrary sentence pairs
  would clear 0.6, and easy-negative accuracy drops (0.812 → 0.750). The prefixes
  may still be right, but they are a **recalibration**, not a drop-in — which is
  why this eval reports them as an arm and the pipeline does not use them.

### Storage: how approximate is the index, and is it even used?

`db/schema.sql` builds an HNSW index over cosine distance, and HNSW is an
*approximate* index — it is fast because it is allowed to miss things, and nothing
above it can tell when it does. `evals/storage_index_eval.py` is the only eval that
needs a live database, because that is the one thing no in-memory stand-in can
imitate: a stand-in ranker is exact by construction and would report the index as
perfect however it behaved.

It fills the table through the **shipped** ingest path (one row per transaction,
exactly as `/process` writes them) with 3,000 rows the query may read plus 3,000
under a second access role it may not, then runs every query four ways per call
shape: `exact` (index scans disabled — the ground truth), `planner` (plain
defaults, i.e. what the application actually gets), `hnsw` (`enable_sort = off`,
which leaves the index as the only ordered path, with `ef_search` swept from 1 to
100), and `random` as the control.

Two findings, and they point the same way:

- **The planner never chooses the index.** On all three call shapes — `/retrieve`
  and `/answer`'s role-only search, the same with a strategy filter, and
  `/evaluate`'s document-scoped search — Postgres gathers the role's chunks
  through the `document_id` foreign key and sorts them exactly. The plans are
  recorded in the artifact, so this is read off `EXPLAIN` rather than inferred.
  A plan's cost does not include detoasting the 3 kB vector it is about to
  compare, so the sort looks cheaper than it is.
- **Forcing the index costs no recall either.** With sorting disabled the index
  *is* used (`forced_uses_hnsw_index` confirms it), and it returns the exact
  top-k at **every** `ef_search` from 1 to 100, at k = 3, 5 and 10. A few thousand
  vectors is a small graph and greedy search on a small graph does not get lost.

So the HNSW index currently pays maintenance on every insert and earns nothing on
any read — search in this system is exact, not approximate, and retrieval quality
has no ANN ceiling under it today. That is a statement about *this scale*, not
about HNSW: raise `_ROWS_PER_ROLE` by an order of magnitude to find where it stops
being true.

**The control is what makes those 1.000s readable.** `random` draws k rows from
the same population and scores 0.000–0.020 against the same exact answer, so the
metric can plainly tell a good answer from a bad one — a recall of 1.000 is a real
1.000 and not a metric stuck on success. The recall figures and the plans reproduce
exactly between runs; the latency columns do not, and are there to show no arm
buys its recall with time rather than to rank the arms. (The extraction eval is
deterministic by construction — nothing in it calls a live service. The embedding
eval reproduced byte for byte across repeat runs here, but it is only as
reproducible as Ollama's embeddings are.)

The run also measures the ingest path it uses: **55.9 rows per second** in the
committed artifact (46–56 across runs), one chunk per transaction with HNSW
maintenance included. That is the real cost of the "write each chunk as it is
produced" choice in `/process`, which trades throughput for holding a single chunk
in memory at a time.

### Retrieval ranking: where in the list does the answer land?

The **retrieval ranking eval** (`evals/retrieval_ranking_eval.py`) scores the same
two documents against a labelled Q&A set (`evals/data/sample_qa.json`, 7 and 8
questions) at `k=3` and `k=5`, reporting recall@k, MRR and nDCG@k per strategy. It
drives the real `Evaluation` service against an in-memory stand-in for pgvector, so
the numbers are the ones `/evaluate` reports and no database is needed.

Its finding is that **the strategy `/evaluate` keeps is not the best-ranked one**,
on either document. On the flat sample at `k=3`, `fixed-64` wins on answer
similarity (`0.762`) and is kept — yet it has the worst ranking in the table
(recall `0.738`, MRR `0.786`, nDCG `0.771`), while `structural` sits `0.003` behind
on similarity (`0.759`) and is perfect on all three. On the structured document
`structural` is kept (`0.803`) but surfaces only half the relevant chunks at
`k=3` (recall `0.498`, rising to `0.850` at `k=5`), where `semantic` reaches recall
`1.000` and nDCG `0.989` at a much lower `0.658` similarity. Selection is
deliberately unchanged by this work — the eval measures the current rule rather
than replacing it — but it makes revisiting that rule a question with numbers
behind it. Read recall with the chunk counts in view: a strategy whose whole
document is smaller than `k` retrieves everything and scores `1.000` for free.

### Answer faithfulness: is the answer grounded?

`/answer` tells the model to use only the retrieved context and to cite it. That
it *does* is a quality claim, so it is measured rather than asserted
(`services/generation/faithfulness.py`). The answer is split into sentence-level
claims, each claim is embedded, and it counts as grounded when it is close enough
to a **context sentence** — not to a whole chunk, whose embedding is dominated by
its general topic and will happily match an invented claim on the right subject.
No LLM judge is involved, so the eval stays deterministic, free and offline, the
same reasoning that keeps `/evaluate` LLM-free.

A faithfulness score on its own proves nothing, so every question is answered
three ways — changing only what the generator is shown — and all three are scored
against the *same* context. `distractor` gets the least similar chunks in the
document; `closed_book` gets none at all and is a control, not a code path
(`/answer` never generates without context):

| condition | faithfulness | mean support |
| --- | --- | --- |
| **grounded** | **0.92** / **1.00** | **0.92** / **0.85** |
| closed_book | 0.42 / 0.19 | 0.70 / 0.68 |
| distractor | 0.58 / 0.00 | 0.76 / 0.51 |

*(`sample.txt` / `structured_sample.txt`; gemma2:2b, `nomic-embed-text`
embeddings. Regenerate with the command above.)*

Grounded answers sit above both controls on both metrics, on both documents —
that separation is what says the measurement works. The two controls do **not**
hold a stable order against each other: `distractor` scores above `closed_book`
on `sample.txt` and below it on `structured_sample.txt`, and the pair swapped
between runs as well. So the grounded-vs-ungrounded gap is the finding; the
ranking *among* the ungrounded conditions is noise at this sample size, and is
not evidence of anything.

**Read one run as one sample.** Generation is seeded, which narrows the spread but
does not make it bit-identical — across repeat runs the flat document's
`faithfulness` moved by up to 0.33, while the ordering above held every time. The
ordering is the finding; the digits are not.

Three things worth naming:

- **Citations are valid but rare.** Across ~100 scored claims the model never
  cited a chunk that was not in its context (`citation_validity` 1.00) — but it
  cited anything at all on only a quarter of grounded claims. The prompt asks for
  citations and mostly does not get them, which is a prompt finding, not a
  metric one.
- **`cited_support` is the noisiest number** in the table, precisely because
  coverage is that low: it averages over one or two claims per condition, so it
  is omitted above and read from the artifact rather than leaned on.
- **The support threshold is calibrated, not guessed.** The eval sweeps it every
  run and records the sweep in the artifact. `0.75` is the highest cut that still
  accepts essentially every grounded claim; a higher cut can show a wider
  grounded-vs-distractor gap purely by rejecting real grounding, which is why the
  gap is a check and not the objective. It is specific to `nomic-embed-text` and
  fitted on a small set — which is why `mean_support`, needing no threshold, is
  the number to trust.


**CI.** Every pull request touching `backend/**` runs the same gates on GitHub
Actions, against a lockfile-pinned install: `ruff format --check`, `ruff check`,
`mypy`, and the fast pytest tier
([`.github/workflows/backend-ci.yml`](.github/workflows/backend-ci.yml)). The
integration tests need a live database and are excluded there — the deployed
stack is verified separately. Pull requests touching `frontend/**` run the mocked
Playwright suite
([`.github/workflows/frontend-e2e.yml`](.github/workflows/frontend-e2e.yml)).

**Pre-commit hook:** a gitleaks secret scan runs on commit. Enable the repo's
hooks in a fresh clone with `git config core.hooksPath .githooks` (requires
[gitleaks](https://github.com/gitleaks/gitleaks#installing) installed). See
[CLAUDE.md](CLAUDE.md) for the full contributor conventions.

## Frontend (Angular)

A single-page [Angular 20](https://angular.dev) app (standalone components) in
[`frontend/`](frontend/) that drives the four backend endpoints from two tabs:

- **Ask** (`/user`) — for readers. Enter a question and either **Answer**
  (`POST /answer`, a grounded reply plus its cited source chunks) or **Retrieve**
  (`POST /retrieve`, the raw ranked chunks). Optional top-K and chunking-strategy
  filter.
- **Admin** (`/admin`) — for maintainers. **Upload &amp; process** a document —
  PDF, DOCX, HTML or plain text —
  (`POST /process`, with optional chunk size, page exclusions, and structural
  section patterns — one regex per line — plus their word bounds) and then
  **Evaluate** the stored strategies (`POST /evaluate`) against a list of
  question / expected-answer pairs; the upload pre-fills the document id, and the
  result table shows each strategy's answer similarity, hit rate, and which one
  was kept.

The **access role** is set once in the header and applied to every request. In
every setup the browser talks to a single origin — the four API paths are
proxied to the backend — so no CORS configuration is needed.

**In the Docker stack (recommended).** `docker compose up -d --build` builds and
runs the frontend as the `frontend` service: an nginx container
([`frontend/Dockerfile`](frontend/Dockerfile)) that serves the compiled SPA and
reverse-proxies `/process`, `/evaluate`, `/retrieve` and `/answer` to `app:8000`
over the internal network (see [`frontend/nginx.conf`](frontend/nginx.conf)).
Open <http://localhost:4200> (override with `FRONTEND_PORT`).

**Dev server (for frontend work; Node 20+).** For live reload while editing the
UI, run against a backend that is already up:

```bash
cd frontend
npm install
npm start          # dev server on http://localhost:4200
```

Here the Angular dev server does the same proxying via
[`frontend/proxy.conf.json`](frontend/proxy.conf.json), so start the backend
first (`docker compose up -d --build`, or run the API directly). `npm run build`
produces the static bundle the image serves. To point the app at a backend on a
different origin instead of proxying, set `API_BASE` in
[`frontend/src/app/core/api-config.ts`](frontend/src/app/core/api-config.ts).

**Tests.** End-to-end tests use [Playwright](https://playwright.dev)
(`frontend/e2e/`). `npm run e2e` runs the fast, offline suite — the API is
stubbed in-browser, so no backend is needed — and runs in CI on frontend
changes. `npm run e2e:stack` runs against the live Compose stack to check what
only the deployment proves (the nginx SPA fallback and the reverse-proxy hop);
it needs the stack up and is run by the `deploy-verify` agent. First run
`npm run e2e:install` to fetch the browser. Angular component unit specs run
under `npm test` (karma).

## Roadmap

Planned but **not yet implemented**:

- **More chunking strategies** — recursive and LLM-based, each behind the existing
  `Chunker` interface so they plug into the same pipeline as the fixed-size,
  semantic and structural strategies.
- **Retrieval-driven strategy selection** — `/evaluate` now reports rank-aware
  metrics (recall@k / MRR / nDCG) beside answer similarity, and they show the kept
  strategy is sometimes not the best-ranked one. Whether selection should weigh them
  is an open question, deliberately left separate from reporting them. An in-loop
  **LLM judge** for answer correctness is deliberately **out of
  scope** for the online endpoint: the scorer stays open-source and cost-free by
  using local embedding similarity, and the Q&A pairs are authored externally (e.g.
  by an LLM offline). A fully-local, offline LLM-judge eval is sketched separately —
  see [Proposal: LLM-judge evaluation with RAGAS](#proposal-llm-judge-evaluation-with-ragas).
- **Richer document & role categorization** — finer-grained document categories
  and user roles, so retrieval and the augmented prompt are scoped precisely to
  each user for more relevant, on-target answers, instead of a single flat
  `access_role`.
- **Extraction:** OCR (Tesseract) and richer extraction (Docling).
- **Web scraping:** Firecrawl / headless-browser / BeautifulSoup ingestion.
- **Recalibrating for `nomic-embed-text`'s task prefixes.** The
  [embedding eval](#embedding-quality-does-close-mean-means-the-same) shows the
  model's documented `search_query:` / `search_document:` prefixes lift paraphrase
  similarity — and lift arbitrary-pair similarity further, putting 85% of the corpus
  above `ANSWER_MATCH_THRESHOLD`. Adopting them means re-fitting both thresholds
  and re-running the retrieval and faithfulness evals; it is a change with a
  measured cost, not a one-line switch.
- **A meaning-aware relevance signal.** No embedder tested — and no lexical
  baseline — separates a claim from its reversal (0 of 16 hard triplets). Anything
  that would (a cross-encoder, an entailment model, the
  [RAGAS judge](#proposal-llm-judge-evaluation-with-ragas) below) is the same
  open question `REQ-EVL-05` is blocked on.
- **Validation:** LLM-based output validation alongside the Pydantic schemas.

## Proposal: LLM-judge evaluation with RAGAS

> **Status: proposal — not implemented.** This section sketches an *optional*,
> deeper evaluation that would run **alongside** (not replace) the current
> embedding-similarity `/evaluate` and the embedding-based
> [answer-faithfulness eval](#answer-faithfulness-is-the-answer-grounded). No
> RAGAS code exists in the repo.

### Why consider it

The current `/evaluate` ranks chunking strategies by how closely retrieved chunks
match a caller-supplied expected answer, using only local embeddings — cheap,
reproducible, and LLM-free (see [Using the API](#using-the-api)). What it *cannot*
see is **answer quality**: whether an answer *generated* from the retrieved
context is faithful (grounded, no hallucination) and actually relevant to the
question.

Part of that gap is now closed offline:
[Answer faithfulness](#answer-faithfulness-is-the-answer-grounded) measures
grounding with embedding similarity between an answer's claims and its context
sentences. What it still cannot do is read **entailment** — a claim that
contradicts the context while resembling it scores as supported, and relevancy to
the question is not measured at all. That is the remaining case for a judge model.
[RAGAS](https://docs.ragas.io) is the standard framework for those RAG-quality
metrics, and it can run **fully locally** against Ollama, so it fits the project's
open-source, no-external-API constraint.

### What RAGAS would add

RAGAS scores a dataset of `question` / `retrieved_contexts` / generated `response`
/ `reference` (ground-truth answer). The metrics relevant here:

| Metric | Needs an LLM? | What it measures |
| --- | --- | --- |
| `SemanticSimilarity` | No (embeddings) | Generated answer vs reference answer — close to today's metric, but on the *answer*, not the context |
| `NonLLMContextRecall` / `…Precision` | No | Retrieved contexts vs **reference contexts** (gold chunk labels) |
| `LLMContextPrecision` / `ContextRecall` | Yes | Whether retrieved contexts are relevant to / support the answer |
| `Faithfulness` | Yes | Is the generated answer grounded in the retrieved context (no hallucination)? |
| `ResponseRelevancy` | Yes | Does the generated answer actually address the question? |
| `FactualCorrectness` | Yes | Generated answer vs reference, claim by claim |

The LLM-judged rows (faithfulness, relevancy, context precision/recall) are the
ones that add signal beyond today's method — and they need an LLM judge, plus a
**generated answer** the current endpoint deliberately never produces.

### The gap vs today's design

- **A generation step is required.** RAGAS's answer-quality metrics score a
  `response`. Today's `/evaluate` retrieves but never generates. The proposal must
  add, per (strategy, question), a generate-from-context step (the same
  Ollama model `/answer` already uses).
- **Non-LLM RAGAS mostly overlaps what we have.** `NonLLMContext*` needs
  **reference contexts** (labelled gold chunks) we don't collect; `SemanticSimilarity`
  needs a generated answer. So the no-LLM subset adds little without new labels.

### Proposed design

Keep it **out of the online request path** — RAGAS is async, LLM-heavy, and
non-deterministic, which does not belong in a `/evaluate` HTTP call. Instead add a
reproducible offline eval, consistent with the existing `backend/evals/` artifacts:

- **`backend/evals/ragas_chunking_eval.py`** — for each stored strategy: retrieve per
  question (reuse `PostgresStorage.search_chunks`, confined to the document +
  strategy), generate an answer from the retrieved context (reuse
  `backend/services/generation`), assemble a RAGAS dataset, and score it.
- **Fully local wiring** — point RAGAS at Ollama for both judge and embeddings via
  `langchain_ollama` + RAGAS's `LangchainLLMWrapper` / `LangchainEmbeddingsWrapper`.
  No external API, no per-call cloud cost.
- **Output** — a regenerable `backend/evals/results/ragas_chunking.json` (per-strategy
  metric table + winner), the same "scores as artifacts" pattern the other evals
  follow. Optionally, a strategy winner could feed the same prune step `/evaluate`
  uses today.

### Trade-offs and open questions

- **Dependency weight** — RAGAS pulls in `ragas`, `langchain`, `datasets`, etc.:
  a large jump from the current lean stack. Likely an optional dependency group so
  the core app/tests stay slim.
- **Judge quality vs cost** — a small local judge (`gemma2:2b`) is a weak, noisier
  grader than a frontier model; a larger local model (e.g. `gpt-oss:20b`) is better
  but heavy on this hardware. Metric reliability is bounded by the judge.
- **Reproducibility** — LLM-judged metrics vary run to run; pin the model + a low
  temperature and treat the numbers as indicative, not exact (unlike the current
  deterministic embedding score).
- **Latency** — generation + multiple LLM-judge calls per (strategy, question) make
  this minutes-scale, another reason it stays an offline eval, not an endpoint.

### Decision needed before building

Whether to (a) run RAGAS **fully local** (open-source, no external $, but real
compute + a weak local judge), or (b) allow an external judge API for stronger,
more reliable metrics at per-call cost. The project's current stance favours (a);
this proposal assumes (a) unless decided otherwise.
