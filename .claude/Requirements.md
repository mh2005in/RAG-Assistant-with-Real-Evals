# Requirements

The requirement register for the RAG Assistant. Every requirement has a stable
ID, a testable acceptance criterion, a status, and **evidence** — the code, test,
or eval artifact that proves it. Product prose lives in [README.md](../README.md);
this file is the checklist that prose is measured against.

**Maintained by:** the `add-requirement` and `sync-status` skills, and the
`requirements-analyst` agent. Don't hand-edit statuses — they are derived from
evidence (see [Delivery-Approach.md](Delivery-Approach.md)).

## How to read this

| Field | Meaning |
| --- | --- |
| **ID** | Stable identifier, `REQ-<STAGE>-<NN>`. Never renumber; retire instead. |
| **Status** | `Done` (shipped + evidenced) · `Partial` (works, gaps listed) · `Planned` (agreed, not built) · `Proposed` (needs a decision first) |
| **Acceptance** | The observable condition that makes it Done. If you can't test it, it isn't a requirement yet. |
| **Evidence** | Code path, test, or eval artifact. `—` for anything not yet built. |

Stage prefixes follow the pipeline: `EXT` extraction · `CHK` chunking ·
`EMB` embedding · `STO` storage · `RET` retrieval · `GEN` generation ·
`EVL` evaluation · `API` service surface · `SEC` access and safety · `UI` frontend ·
`OPS` stack and config · `QUA` quality gates · `DOC` documentation.

**The eval rule overrides everything below:** per [CLAUDE.md](../CLAUDE.md), a
pipeline-stage requirement (`EXT`/`CHK`/`EMB`/`STO`/`RET`/`GEN`) can't reach
`Done` without a real eval measuring it — see `REQ-EVL-02`.

---

## EXT — Extraction

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-EXT-01 | Detect a PDF upload and extract its text page by page, with per-page stats (chars, words, raw sentence count, token estimate). | Done | `POST /process` on a PDF returns `processed: true` and `doc_type: "pdf"`; a non-PDF is rejected. | [file_processing.py](../backend/services/file_processing.py), [test_file_processing.py](../backend/tests/test_file_processing.py) |
| REQ-EXT-02 | Exclude pages before chunking, by page number and/or inclusive range, without shifting the numbering of the pages that remain. | Done | Excluding page 1 and pages 10–12 drops exactly those pages for **every** strategy; malformed input is a field-scoped 422. | [pages.py](../backend/dtos/requests/pages.py), [test_page_exclusion.py](../backend/tests/test_page_exclusion.py) |
| REQ-EXT-03 | OCR scanned PDFs (Tesseract) so image-only pages yield text. | Planned | A scanned PDF with no text layer produces chunks; an eval compares OCR'd against native extraction quality. | — |
| REQ-EXT-04 | Ingest non-PDF document types (DOCX, HTML, plain text) behind the same extraction step. | Planned | `POST /process` accepts the type and reports it in `doc_type`; per-page stats degrade gracefully for paginationless formats. | — |
| REQ-EXT-05 | Ingest web pages (Firecrawl / headless browser / BeautifulSoup) as documents. | Planned | A URL can be processed into stored, retrievable chunks; scraped content is never committed to the repo. | — |

## CHK — Chunking

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-CHK-01 | Every chunking strategy sits behind one `Chunker` interface so strategies stay swappable and comparable. | Done | A new strategy is added by implementing `Chunker` alone — no changes to extraction, embedding, or storage. | [chunking/base.py](../backend/services/chunking/base.py) |
| REQ-CHK-02 | Fixed-size chunking in **words**, with a caller-tunable `chunk_size` (default 200). | Done | A given chunk size yields windows of at most that many words; a non-positive size is a 422. | [fixed_size.py](../backend/services/chunking/fixed_size.py), [test_fixed_size_chunker.py](../backend/tests/test_fixed_size_chunker.py) |
| REQ-CHK-03 | Semantic chunking that breaks where consecutive sentences drift apart in embedding space. | Done | Boundaries land on topic shifts in prose that carries no markup; measured against the fixed-size baseline. | [semantic.py](../backend/services/chunking/semantic.py), [chunking_strategies.json](../backend/evals/results/chunking_strategies.json) |
| REQ-CHK-04 | Structural chunking on a document's own markers (headings, numbered sections, Chapter/Section/Appendix labels, roman and lettered items, ALL-CAPS titles), with caller-supplied patterns and word bounds. | Done | A structured document beats the baseline on the coherence score; a marker-free document falls back to paragraphs; an uncompilable regex is a 422. | [structural.py](../backend/services/chunking/structural.py), [test_structural_chunker.py](../backend/tests/test_structural_chunker.py) |
| REQ-CHK-05 | `/process` runs **every** implemented strategy and stores all of their chunks against one document row — the caller never picks a strategy, and nothing is scored or dropped at ingest. | Done | The `/process` response lists each strategy and its chunk count; the `chunks` table holds all of them side by side. | [file_processing.py](../backend/services/file_processing.py), [process.py](../backend/dtos/responses/process.py) |
| REQ-CHK-06 | Recursive chunking (split on a descending list of separators) behind the `Chunker` interface. | Planned | Registered in the strategy set, scored by the comparison eval, and reported by `/process` like the rest. | — |
| REQ-CHK-07 | LLM-based chunking (a model proposes the boundaries) behind the `Chunker` interface. | Planned | As above, plus a documented cost and latency note — it would be the only strategy spending LLM calls at ingest. | — |

## EMB — Embedding

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-EMB-01 | Embed chunks and queries through one `Embedder` interface, backed by local Ollama (`nomic-embed-text`, 768-dim), configurable by environment. | Done | No external API key is needed anywhere in the pipeline; the model is swappable via `OLLAMA_EMBED_MODEL`. | [ollama_embedder.py](../backend/services/embedding/ollama_embedder.py), [test_ollama_embedder.py](../backend/tests/test_ollama_embedder.py) |
| REQ-EMB-02 | Support an embedding model of a different dimension without hand-edited DDL. | Planned | Changing the embed model to a non-768-dim model works without a manual schema change (today the `vector(768)` column forces one). | — |

## STO — Storage

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-STO-01 | Persist documents and embedded chunks in PostgreSQL + pgvector, with an HNSW cosine index for similarity search. | Done | The schema creates `documents`, `chunks`, the FK cascade and the HNSW index; integration tests read and write them. | [schema.sql](../backend/db/schema.sql), [test_postgres_storage.py](../backend/tests/test_postgres_storage.py) |
| REQ-STO-02 | Re-processing the same document (same name + access role) reuses its row and **replaces** its chunks rather than accumulating duplicates. | Done | The unique constraint holds; two `/process` calls leave one `documents` row and one generation of chunks. | [schema.sql](../backend/db/schema.sql), [postgres.py](../backend/services/storage/postgres.py) |
| REQ-STO-03 | Every chunk records the strategy that produced it, numbered from 0 **per strategy**, so several strategies coexist under one document. | Done | The unique constraint spans document, strategy and index; losing strategies are deleted in bulk without touching `documents`. | [schema.sql](../backend/db/schema.sql) |

## RET — Retrieval

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-RET-01 | `POST /retrieve` embeds a query and returns the top-k most similar chunks with scores, restricted to the caller's access role. | Done | Results carry document name, strategy, page number, text and score; a mismatched role returns nothing. | [retrieval.py](../backend/services/retrieval.py), [test_retrieval.py](../backend/tests/test_retrieval.py) |
| REQ-RET-02 | Retrieval can be confined to one chunking strategy, so the same document chunked several ways is comparable. | Done | Passing a strategy searches only that strategy's chunks, on both `/retrieve` and `/answer`. | [retrieval.py](../backend/services/retrieval.py) |

## GEN — Generation

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-GEN-01 | `POST /answer` retrieves context, augments the prompt with it, and returns a grounded answer plus its source chunks. | Done | The response carries the answer and the sources it was grounded in; citations refer to those sources. | [answering.py](../backend/services/answering.py), [test_answering.py](../backend/tests/test_answering.py) |
| REQ-GEN-02 | Generation runs through one `LLMClient` interface backed by local Ollama, model set by environment (default `gemma2:2b`). | Done | No external API key; a larger model can be swapped in by environment alone; tests override the client with a fake. | [ollama_client.py](../backend/services/generation/ollama_client.py), [test_ollama_client.py](../backend/tests/test_ollama_client.py) |

## EVL — Evaluation

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-EVL-01 | `POST /evaluate` scores a stored document's strategies against caller-supplied Q&A pairs, ranks them by answer similarity, reports hit rate, keeps the winner's chunks and deletes the rest. | Done | The response ranks every stored strategy best-first with exactly one marked selected; afterwards the document holds only that strategy's chunks. A role mismatch is a 404. | [evaluation.py](../backend/services/evaluation.py), [test_evaluation.py](../backend/tests/test_evaluation.py) |
| REQ-EVL-02 | Every pipeline stage is measured by a **reproducible, checked-in** eval whose results are regenerable artifacts, not screenshots. | Partial | Chunking is covered (fixed-size sweep plus the three-strategy comparison, results committed as JSON). Extraction, embedding, storage, retrieval and generation have no standalone eval yet. | [evals/](../backend/evals/), [results/](../backend/evals/results/) |
| REQ-EVL-03 | Chunking strategies are comparable **without labels**, via a cohesion/separation score. | Done | The comparison eval reports one score per strategy per dataset, over a flat and a structured document. | [coherence.py](../backend/services/chunking/coherence.py), [test_coherence.py](../backend/tests/test_coherence.py) |
| REQ-EVL-04 | Rank-aware retrieval metrics (recall@k, MRR, nDCG) over the same labelled Q&A set `/evaluate` already takes. | Planned | Reported alongside answer similarity and hit rate and recorded as a regenerable artifact; ranking behaviour unchanged unless deliberately switched. | — |
| REQ-EVL-05 | A fully-local RAGAS LLM-judge eval (faithfulness, response relevancy, context precision and recall), run **offline** and never in the request path. | Proposed | Blocked on the decision recorded in the README proposal: a local judge (open-source, weaker) against an external judge API (stronger, per-call cost). | [README proposal](../README.md#proposal-llm-judge-evaluation-with-ragas) |
| REQ-EVL-06 | Answer-faithfulness measurement for the generation stage — is the answer grounded in its cited sources? | Planned | An offline eval scores generated answers against their retrieved context; REQ-GEN-01 stays `Done` only while this holds. | — |

## API — Service surface

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-API-01 | Four endpoints — `/process`, `/evaluate`, `/retrieve`, `/answer` — documented by OpenAPI at `/docs`. | Done | `GET /openapi.json` returns 200 and lists all four. | [api.py](../backend/api.py), [test_api.py](../backend/tests/test_api.py) |
| REQ-API-02 | Every request and response is a Pydantic model kept in `dtos/requests/` and `dtos/responses/` — never defined inline in a route. | Done | No DTO class is declared in `api.py`; routes import them. | [dtos/](../backend/dtos/) |
| REQ-API-03 | A malformed JSON-carrying form field returns a 422 whose error location names the field, not a bare type error. | Done | Bad page-exclusion or structural input reports the field name in `loc`. | [api.py:52](../backend/api.py) |
| REQ-API-04 | Route handlers stay thin: processing lives in `services/`, one service class per endpoint, dependencies injected per request. | Done | Each route delegates to one service; storage and the LLM client are FastAPI dependencies that tests override with fakes. | [api.py](../backend/api.py), [conftest.py](../backend/tests/conftest.py) |

## SEC — Access and safety

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-SEC-01 | A document is stored under one access role; `/retrieve`, `/answer` and `/evaluate` only touch documents matching the caller's role. | Done | A query with the wrong role returns no chunks, and `/evaluate` returns 404. | [postgres.py](../backend/services/storage/postgres.py), [schema.sql](../backend/db/schema.sql) |
| REQ-SEC-02 | Finer-grained document categories and user roles, so retrieval and the augmented prompt are scoped precisely per user rather than by one flat role. | Planned | A document carries a category and multiple roles; retrieval filters on both; the join-table note in the schema is resolved. | — |
| REQ-SEC-03 | LLM output validation alongside the Pydantic schemas (the validation pipeline stage). | Planned | A generated answer that fails validation is rejected or repaired rather than returned as-is, and the behaviour is measured by an eval. | — |
| REQ-SEC-04 | No secret, PII, source document, scraped content, embedding, or DB dump is ever committed. | Done | gitleaks runs on every staged diff via the pre-commit gate and data paths are gitignored. PII stays a **human** check — gitleaks matches secret patterns only. | [.githooks/pre-commit](../.githooks/pre-commit), [CLAUDE.md](../CLAUDE.md) |

## UI — Frontend

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-UI-01 | An **Ask** tab where a reader enters a question and gets either a grounded answer with cited sources or the raw ranked chunks, with optional top-K and strategy filter. | Done | Both actions render their results; covered by the mocked E2E suite. | [user/](../frontend/src/app/user/), [user.spec.ts](../frontend/e2e/mocked/user.spec.ts) |
| REQ-UI-02 | An **Admin** tab that uploads and processes a PDF (chunk size, page exclusions, structural patterns and bounds) and then evaluates the stored strategies against Q&A pairs, showing similarity, hit rate, and the kept strategy. | Done | The upload pre-fills the document id for the evaluate form; the result table marks the winner. | [admin/](../frontend/src/app/admin/), [admin.spec.ts](../frontend/e2e/mocked/admin.spec.ts) |
| REQ-UI-03 | The access role is set once in the header and applied to every request. | Done | Changing the role changes what subsequent calls can see. | [session.service.ts](../frontend/src/app/core/session.service.ts) |
| REQ-UI-04 | The browser always talks to a single origin — the API paths are proxied — so no CORS configuration exists anywhere. | Done | nginx proxies in the stack, the Angular dev server proxies in development; there is no CORS middleware in `api.py`. | [nginx.conf](../frontend/nginx.conf), [proxy.conf.json](../frontend/proxy.conf.json) |

## OPS — Stack and configuration

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-OPS-01 | The whole system runs from one command as frontend + app + Postgres/pgvector + Ollama, each with a healthcheck, plus a one-shot model puller. | Done | All four containers report healthy, the puller exits 0, and both `/openapi.json` and the SPA root serve. | [docker-compose.yml](../docker-compose.yml) |
| REQ-OPS-02 | All configuration is environment variables with `.env.example` kept in parity; services address each other by compose service name, never `localhost` or a hardcoded URL. | Done | The database and Ollama URLs are built in compose; every variable used appears in `.env.example`. | [.env.example](../.env.example), [docker-compose.yml](../docker-compose.yml) |
| REQ-OPS-03 | CPU and CUDA are switchable with one variable, with CPU the default that works everywhere. | Done | Setting the GPU count to `all` uses the GPU and `0` runs on CPU, verifiable through `ollama ps`. | [docker-compose.yml](../docker-compose.yml), [README](../README.md#cpu-or-cuda) |
| REQ-OPS-04 | Any stack-affecting change is verified by a real deploy — build, healthchecks, and a served API — before it is called done. | Done | The `deploy-verify` agent runs the stack and the stack E2E suite, and signals a clean pass for the cleanup hook. | [deploy-verify.md](agents/deploy-verify.md) |

## QUA — Quality gates

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-QUA-01 | Formatting, linting and type checking are automatic rather than remembered: format and lint-fix after every edit, type check at the end of every turn. | Done | Configured as `PostToolUse` and `Stop` hooks. | [settings.json](settings.json) |
| REQ-QUA-02 | Unit tests are fast and offline (external services mocked); anything needing Postgres/pgvector or the network is marked `integration` so the default run stays fast. | Done | 137 fast and 6 integration tests collected; the fast set runs with no database and no network. | [tests/](../backend/tests/), [pyproject.toml](../backend/pyproject.toml) |
| REQ-QUA-03 | The frontend has both a fast offline E2E suite (API stubbed in-browser) and a stack suite proving what only the deployment can — the SPA deep-link fallback and the proxy hop. | Done | 9 mocked specs run with no backend; 3 stack specs run against the live stack. | [e2e/](../frontend/e2e/), [playwright.config.ts](../frontend/playwright.config.ts) |
| REQ-QUA-04 | A commit can't introduce a wrong author, a leaked secret, or a failing fast test. | Done | The pre-commit hook checks the author, runs gitleaks on the staged diff, then runs the fast tests. | [.githooks/pre-commit](../.githooks/pre-commit) |
| REQ-QUA-05 | The mocked frontend E2E suite runs in CI on every PR touching the frontend. | Done | The `frontend-e2e` workflow runs it and uploads the Playwright report as an artifact. | [frontend-e2e.yml](../.github/workflows/frontend-e2e.yml) |
| REQ-QUA-06 | Backend tests, lint and types run in CI on every PR touching the backend. | Planned | The `backend-ci` workflow runs `ruff format --check`, `ruff check`, `mypy` and the fast pytest tier against a lockfile-pinned install, on every PR touching `backend/**`, and reports green. | [backend-ci.yml](../.github/workflows/backend-ci.yml) — built; awaiting its first PR run, which is the green-run evidence |
| REQ-QUA-07 | A bug fix ships with a test that fails without it, and a failing test is never deleted or weakened to make the suite pass. | Done | Convention enforced in review. | [CLAUDE.md](../CLAUDE.md) |

## DOC — Documentation

| ID | Requirement | Status | Acceptance | Evidence |
| --- | --- | --- | --- | --- |
| REQ-DOC-01 | The README describes **what exists today**, updated in the same change as the code rather than as a follow-up. Aspirational work lives under Roadmap until it ships. | Done | Every endpoint, env var, dependency and stack change is reflected in the README at merge time. | [README.md](../README.md), [CLAUDE.md](../CLAUDE.md) |
| REQ-DOC-02 | The delivery documents in `.claude/` — this register, the plan, the architecture, the delivery approach, the status dashboard and the change log — stay in step with the repository. | Done | The `sync-status` skill re-derives statuses from evidence; the `docs-sync` agent flags drift between the README, CLAUDE.md and these files. | [.claude/](.) |
| REQ-DOC-03 | Guidance in CLAUDE.md is judgment, not mechanics: an every-time mechanical check becomes a hook, a task-specific procedure becomes a skill, delegated multi-step work becomes an agent. | Done | New rules are routed to the right home rather than added as always-on prose. | [CLAUDE.md](../CLAUDE.md) |

---

## Traceability summary

| Stage | Done | Partial | Planned | Proposed | Total |
| --- | --- | --- | --- | --- | --- |
| EXT | 2 | 0 | 3 | 0 | 5 |
| CHK | 5 | 0 | 2 | 0 | 7 |
| EMB | 1 | 0 | 1 | 0 | 2 |
| STO | 3 | 0 | 0 | 0 | 3 |
| RET | 2 | 0 | 0 | 0 | 2 |
| GEN | 2 | 0 | 0 | 0 | 2 |
| EVL | 2 | 1 | 2 | 1 | 6 |
| API | 4 | 0 | 0 | 0 | 4 |
| SEC | 2 | 0 | 2 | 0 | 4 |
| UI | 4 | 0 | 0 | 0 | 4 |
| OPS | 4 | 0 | 0 | 0 | 4 |
| QUA | 6 | 0 | 1 | 0 | 7 |
| DOC | 3 | 0 | 0 | 0 | 3 |
| **Total** | **40** | **1** | **11** | **1** | **53** |

Sequencing for everything not yet `Done` is in [Plan.md](Plan.md); live status is
in [Status-Dashboard.md](Status-Dashboard.md).
