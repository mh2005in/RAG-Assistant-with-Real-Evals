# Change Log

Notable changes to the RAG Assistant, newest first. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is
pre-release (`0.1.0`), so entries are grouped by **merge date** rather than by
version tag.

Entries are appended by the `record-change` skill after a merge, seeded from the
merged commits. Each entry names the requirement IDs it closes — see
[Requirements.md](Requirements.md).

---

## Unreleased

Nothing merged since 2026-08-16. Next up is Phase 4 (Measurement depth) — see
[Plan.md](Plan.md).

---

## 2026-08-16

### Added
- **Structural chunking strategy**, wired through the API and the Admin UI
  (`REQ-CHK-04`). Breaks on the markers a document already carries — markdown
  headings, numbered sections, `Chapter`/`Section`/`Appendix` labels, roman and
  lettered items, ALL-CAPS title lines — matched by regex over line starts, with
  no embeddings needed. Callers can override the patterns and the word bounds via
  a `structural` form field; an uncompilable regex is a field-scoped 422.
  Over-long sections split at paragraph, then sentence, then word boundaries; a
  too-short one merges forward; a document with no markers falls back to
  paragraphs.
- A second eval dataset (`structured_sample.txt`) and structural runs in the
  strategy comparison. Structural scores **−0.18** on the structured document
  against −0.31 (semantic) and −0.31 to −0.38 (fixed-size); on flat prose it has
  nothing to find and lands with the rest.

*PR #27*

## 2026-08-01

### Added
- **Playwright E2E for the frontend**, in two tiers (`REQ-QUA-03`, `REQ-QUA-05`):
  a fast offline suite with the four API endpoints stubbed in-browser (runs in CI
  on frontend PRs, no backend needed), and a stack suite that runs against the
  live Compose stack to prove what only the deployment can — the nginx SPA
  deep-link fallback and the reverse-proxy hop.
- **Angular frontend**, wired into the Docker stack (`REQ-UI-01`–`REQ-UI-04`).
  Angular 20 standalone components with an **Ask** tab (`/retrieve`, `/answer`
  with cited sources) and an **Admin** tab (upload and process, then evaluate the
  stored strategies). The access role is set once in the header and applied to
  every request. Served by nginx, which reverse-proxies the API paths to
  `app:8000` — so the browser talks to a single origin and no CORS configuration
  is needed anywhere.

*PR #26, #25*

## 2026-07-31

### Changed
- **Split the repository into `backend/` and `frontend/`.** All Python code,
  `pyproject.toml`/`uv.lock`, the Dockerfile and `db/` moved under `backend/`;
  `uv` commands now run from there. Docker Compose, `.env`, CLAUDE.md and the
  README stay at the root and span both.

### Added
- **`deploy-verify` agent** (`REQ-OPS-04`) — builds the stack, waits for all four
  healthchecks, exercises `/openapi.json` and the SPA root, and runs the stack
  E2E suite. A real deploy, not host-run tests.
- **Post-deploy cleanup hook** — on a clean `deploy-verify` pass, removes Python
  caches, dangling Docker images and build cache, and the session scratchpad.
  A no-op after any other subagent or a failed deploy.

*PR #24*

## 2026-07-30

### Changed
- **Trimmed CLAUDE.md and moved the mechanical checks into hooks**
  (`REQ-QUA-01`, `REQ-DOC-03`). `ruff format` and `ruff check --fix` now run
  after every edit, `mypy` at the end of every turn. The guiding rule: prose is
  for judgment, mechanical every-time checks are hooks, task-specific procedures
  are skills, delegated multi-step work is agents.

*PR #23*

## 2026-07-23

### Added
- **`/evaluate` as a labelled retrieval eval** over caller-supplied Q&A pairs
  (`REQ-EVL-01`). Retrieves per strategy for every question, scores each retrieval
  against the expected answer by cosine similarity, aggregates per strategy with
  pandas, ranks by `answer_similarity`, then **keeps the winner's chunks and
  deletes the rest**. Also reports `hit_rate`. A role mismatch is a 404.
- **Semantic chunking** (`REQ-CHK-03`) — embeds each sentence and breaks where
  consecutive sentences drift apart in meaning, finding topic shifts that nothing
  marks up.
- Documentation of **why `/evaluate` uses embedding similarity rather than an LLM
  judge**: the Q&A pairs are authored externally, so the eval makes no LLM calls
  and stays deterministic, free and repeatable.
- **RAGAS LLM-judge proposal** (`REQ-EVL-05`, still `Proposed`) — an optional,
  fully-local, *offline* eval running alongside the current `/evaluate`, with the
  gap analysis and the open decision written down.

### Changed
- **Decoupled evaluation from chunking** (`REQ-CHK-05`). `/process` now runs every
  strategy and stores all of their chunks unscored against one document row; the
  caller no longer picks a strategy and nothing is dropped at ingest. Scoring
  moved entirely to `/evaluate`, so a document can be re-scored with a new
  question set without re-chunking. Chunks are streamed rather than materialised.
- `/process` returns only what was stored — the strategies and their chunk
  counts — not the chunks themselves.
- Generation model switched to `gpt-oss:20b`, then **defaulted back to
  `gemma2:2b`** (~1.6 GB, comfortable on CPU-only hardware) in the same week.
  `gpt-oss:20b` remains a one-variable swap for bigger machines.

*PR #22, #21, #20, #19, #18, #17*

## 2026-07-21

### Changed
- **Separated `chunk_size` from page exclusion on `/process`** (`REQ-EXT-02`).
  `chunk_size` tunes only the fixed-size candidate; `exclude_pages` is
  strategy-agnostic and applies to the extracted pages before any chunking, so it
  behaves identically for every strategy. Excluded pages don't shift the numbering
  of the pages that remain.

*PR #16*

## 2026-07-19

### Added
- **PostgreSQL + pgvector storage** (`REQ-STO-01`–`03`) — `documents` and `chunks`
  tables, FK cascade, per-strategy chunk numbering, and an HNSW cosine index.
  Documents are unique on `(name, access_role)`, so re-processing replaces chunks
  instead of duplicating rows.
- **`POST /retrieve`** (`REQ-RET-01`) — embeds a query and runs a pgvector cosine
  similarity search over stored chunks, filtered by access role.
- **`POST /answer`** (`REQ-GEN-01`, `REQ-GEN-02`) — retrieve, augment the prompt
  with the retrieved context, generate a cited answer with its sources, using
  local Ollama.
- **Docker Compose stack** (`REQ-OPS-01`) — app + Postgres/pgvector + Ollama, each
  healthchecked, with a one-shot model puller.

### Changed
- **Embeddings moved to local Ollama** (`REQ-EMB-01`), dropping
  `sentence-transformers` and `torch`. The app itself no longer has a GPU
  dependency — Ollama is the only service doing tensor maths.
- README rewritten around the current architecture, with the rule that it stays
  current in the same change as the code (`REQ-DOC-01`).

*PR #15, #14, #13, #12, #11, #10*

## 2026-07-18

### Added
- Embedding stage with a configurable model and device.

### Changed
- **`chunk_size` is now word-based, not character-based** (`REQ-CHK-02`).
- Chunk text and embeddings are clipped in the `/process` response, so a large
  document doesn't return an unusable payload.

*PR #9, #8, #7*

## 2026-07-17

### Added
- **PDF detection and fixed-size chunking** in the file pipeline (`REQ-EXT-01`).
- **Post-merge hook** that removes merged worktrees automatically.
- Repository conventions documented (CLAUDE.md), including the rule that secrets
  and **PII** are placeholdered before committing — gitleaks matches secret
  patterns only, so PII stays a human check.
- PyCharm project configuration tracked.

### Changed
- **Consolidated file processing into a single service class** (`REQ-API-04`) —
  one service class per endpoint, each step a private method, rather than a module
  per step.
- `pydantic` declared as a direct dependency instead of relying on FastAPI's.

*PR #6, #5*

## 2026-07-15

### Added
- Fixed-size chunking request DTO and the `services/` layer (`REQ-API-02`) —
  establishing the split between `dtos/requests/`, `dtos/responses/`, and
  processing logic.

*PR #4*

## 2026-07-13

### Added
- **FastAPI file-processing endpoint** — the first service surface.
- **Project tooling bootstrapped** (`REQ-QUA-04`): `uv`, Ruff, mypy, pytest, and
  the secret-scanning pre-commit hook that also checks the commit author and runs
  the fast tests.

*PR #3, #1*

## 2026-07-10

- Initial README.

---

## Adding an entry

Use the skill, after the merge:

```bash
/record-change
```

It reads the merged commits, drafts the entry, and appends it under the right
date. Then run `/sync-status` so the dashboard and the requirement statuses catch
up.

Writing one by hand instead? Keep to the conventions above:

- **Group by merge date**, newest first, with the PR numbers on a trailing line.
- **`### Added` / `### Changed` / `### Fixed` / `### Removed`** — only the
  sections that apply.
- **Name the requirement IDs** the change closes. An entry with no ID means work
  happened that no requirement asked for — either add the requirement or explain
  why it isn't one.
- **Write what changed for a reader of the system**, not what changed in the
  diff. "Decoupled evaluation from chunking so a document can be re-scored without
  re-chunking" beats "refactored `file_processing.py`".
- **Cite eval numbers** when a change claims an improvement. That's the project's
  standard everywhere else, and the changelog is no exception.
