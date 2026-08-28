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

Nothing merged since 2026-08-23. Phase 4 (Measurement depth) is under way — its
first item, backend CI, has shipped; next are rank-aware retrieval metrics
(`REQ-EVL-04`) and an answer-faithfulness eval for generation (`REQ-EVL-06`).
See [Plan.md](Plan.md).

---

## 2026-08-23

### Added
- **Backend CI** (`REQ-QUA-06`). Every pull request touching `backend/**` now runs
  the gates that previously existed only as local git hooks: `ruff format
  --check`, `ruff check`, `mypy`, and the fast pytest tier (`-m "not
  integration"`), against a lockfile-pinned install. A pull request raised from a
  clone without `core.hooksPath` configured is no longer unguarded. `uv sync
  --frozen` makes a `uv.lock` that has drifted from `pyproject.toml` a CI failure
  rather than a silent re-resolve. The integration tests stay excluded — they need
  a live Postgres/pgvector — so proving the deployed stack remains the
  `deploy-verify` agent's job.
- **Three tests closing gaps the audit found**, taking the fast tier from 137 to
  140. Page exclusion is now asserted against the semantic and structural chunks
  rather than only the fixed ones, and the per-strategy retrieval filter is
  asserted to reach storage from `/retrieve` **and** `/answer` — previously it was
  proven only by a storage-layer integration test that bypassed both endpoints.
  Neither was a bug: the behaviour was correct, but nothing held it in place.

### Changed
- **The delivery loop now names every document it must update** (advances
  `REQ-DOC-02`). Step 6 of `deliver-requirement` listed only the README and the
  architecture document, leaving the register, the plan and the delivery approach
  to judgment. It now enumerates all of them, and adds an explicit search for
  prose that still asserts a gap the change just closed — a "known gap" note or a
  risk-table row will otherwise go on claiming something is missing long after it
  ships. Both copies of the Definition of Done gained the matching line, and
  `Status-Dashboard.md` and `Change-Log.md` are now called out as derived state
  that is never hand-edited in that step.
- **CI actions moved off the deprecated Node.js 20 runtime.** `actions/checkout`,
  `actions/setup-node` and `actions/upload-artifact` were all on `v4`, which is
  `runs.using: node20`; every run warned they were being forced onto Node 24. All
  three are now `v7`. `upload-artifact@v5` is still node20 — node 24 only became
  its default in v6 — so a single-major bump would have left this half-fixed.
  `astral-sh/setup-uv@v10.0.1` was already node24 and is unchanged.
- **The eval rule now gates quality claims, not every requirement in a pipeline
  stage.** As written, it said any `EXT`/`CHK`/`EMB`/`STO`/`RET`/`GEN` requirement
  needed a real eval to be `Done` — which would have demoted ten rows asserting
  things an eval cannot measure, like "a non-PDF is rejected" or "the model is
  swappable by environment". It now gates claims about *how well* something works
  (a strategy's performance, an answer's groundedness); functional contracts in the
  same stage are proven by tests. An evidence audit applied the sharpened rule to
  all 53 rows; `REQ-GEN-01` moves to `Partial` because *grounded* is a quality
  claim nothing currently measures (`REQ-EVL-06` is the eval that would close it).

*PR #29, #30, #31, #32, #33*

## 2026-08-21

### Added
- **Delivery documents, skills and agents** under [`.claude/`](.) (`REQ-DOC-02`,
  `REQ-DOC-03`). The requirements register, plan, architecture, delivery approach,
  status dashboard and this change log now live in the repository. Every
  requirement carries a stable `REQ-<STAGE>-<NN>` id, a testable acceptance
  criterion and an evidence column — nothing gets built without an id, and a
  status is derived from evidence rather than declared. Four skills drive the
  delivery loop (`deliver-requirement`, `add-requirement`, `sync-status`,
  `record-change`) and four agents do the delegated work inside it
  (`requirements-analyst`, `eval-runner`, `docs-sync`, `deploy-verify`). CLAUDE.md
  gained the rule that routes a proposed convention to its right home — always-on
  prose, a hook, a skill, or an agent.

*PR #28*

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
