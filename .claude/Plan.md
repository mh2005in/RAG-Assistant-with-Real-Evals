# Plan

Sequencing for the requirements in [Requirements.md](Requirements.md). Phases 0–3
are shipped and recorded here as the built foundation; phases 4–7 are the forward
plan.

**How this file is used:** every phase names the requirements it closes, what it
depends on, and the exit criteria that make it done. Work is pulled from the
earliest open phase — see [Delivery-Approach.md](Delivery-Approach.md) for how a
single requirement is taken from open to merged.

---

## Sequencing rationale

Three constraints set the order, and they matter more than any individual feature:

1. **Measurement before breadth.** The project's premise is that every stage is
   measured. Chunking and generation now have real evals; extraction, embedding,
   storage and retrieval still do not (`REQ-EVL-02` is `Partial`).
   Adding more ingestion formats or strategies before the measurement layer exists
   means adding things we can't tell are working — which is the exact failure mode
   this project was built to avoid. Phase 4 comes first for that reason.
2. **Gates before contributors.** Backend tests, lint and types used to run only
   as local hooks — fine for one machine, not fine for anything else — so
   `REQ-QUA-06` was folded into Phase 4 as small, cheap insurance and taken
   first. The `backend-ci` workflow now re-runs those gates on every backend PR.
3. **Schema changes early in their phase.** `REQ-EMB-02` and `REQ-SEC-02` both
   touch the database, and both are cheaper before more data shapes depend on
   them.

---

## Phase 0 — Foundation ✅ *shipped 2026-07-13 → 2026-07-18*

Tooling, the service skeleton, and the first chunking strategy.

- Bootstrapped `uv`, Ruff, mypy, pytest, and the secret-scanning pre-commit gate
- FastAPI service with a file-processing endpoint
- PDF detection and extraction; fixed-size chunking, word-based (`REQ-CHK-02`)
- Services layer and DTO folders established (`REQ-API-02`, `REQ-API-04`)

**Exit:** a PDF could be uploaded and chunked, with the conventions in place.

## Phase 1 — The local RAG loop ✅ *shipped 2026-07-18 → 2026-07-19*

Making it an actual RAG system, entirely local.

- Embedding stage, then the switch to local Ollama, dropping sentence-transformers
  and torch (`REQ-EMB-01`)
- Postgres + pgvector storage with the HNSW cosine index
  (`REQ-STO-01`–`03`)
- `/retrieve` similarity search (`REQ-RET-01`)
- `/answer`: retrieve → augment → generate with citations (`REQ-GEN-01`,
  `REQ-GEN-02`)
- Packaged the app and brought up the Compose stack (`REQ-OPS-01`)

**Exit:** ingest → store → retrieve → answer worked end to end with no external
API key.

## Phase 2 — Comparable strategies ✅ *shipped 2026-07-21 → 2026-08-16*

The evaluation-driven core: several strategies, measured against each other.

- Semantic chunking (`REQ-CHK-03`) and structural chunking (`REQ-CHK-04`)
- Decoupled evaluation from chunking — `/process` stores every strategy unscored
  (`REQ-CHK-05`)
- `/evaluate` as a labelled retrieval eval over caller Q&A, keeping the winner
  (`REQ-EVL-01`)
- Label-free cohesion/separation scoring and the checked-in eval artifacts
  (`REQ-EVL-03`, and the chunking half of `REQ-EVL-02`)
- Page exclusion separated from chunk size (`REQ-EXT-02`)

**Exit:** three strategies scored on the same data, results committed as
regenerable JSON.

## Phase 3 — Product surface and deployability ✅ *shipped 2026-07-30 → 2026-08-01*

Making it usable and provably deployable.

- Split the repo into `backend/` and `frontend/`
- Angular SPA with Ask and Admin tabs (`REQ-UI-01`–`04`)
- Playwright E2E, mocked and stack tiers (`REQ-QUA-03`), with the mocked suite in
  CI (`REQ-QUA-05`)
- `deploy-verify` agent and the post-deploy cleanup hook (`REQ-OPS-04`)
- Moved mechanical checks out of prose and into hooks (`REQ-QUA-01`,
  `REQ-DOC-03`)

**Exit:** one command brings up a stack that a browser can drive, and a change to
it is verified by a real deploy.

---

## Phase 4 — Measurement depth ⬅ **in progress**

**Goal:** close `REQ-EVL-02` — every stage measured, not just chunking — and make
the backend gates run somewhere other than one laptop.

| # | Requirement | Notes |
| --- | --- | --- |
| 4.1 | `REQ-QUA-06` | ✅ **Shipped 2026-08-23** (PR #29). Backend CI workflow: `ruff format --check`, `ruff check`, `mypy` and the fast tests on `backend/**`. |
| 4.2 | `REQ-EVL-04` | Rank-aware metrics (recall@k, MRR, nDCG) over the Q&A set `/evaluate` already takes. Report alongside the current metrics; **don't change the ranking behaviour** in the same change. |
| 4.3 | `REQ-EVL-06` | ✅ **Shipped.** Answer-faithfulness eval for generation: claims vs context sentences, embedding-based, three conditions (grounded / distractor / closed-book). The first eval covering the generation stage; also closed `REQ-GEN-01`'s grounding gap. |
| 4.4 | `REQ-EVL-05` | RAGAS LLM-judge eval. **Blocked on a decision** (local judge vs external judge API) — see the README proposal. Resolve the decision before any code. |
| 4.5 | `REQ-EVL-02` | Retrieval and embedding evals to finish the stage coverage. Flips this requirement from `Partial` to `Done`. |

**Dependencies:** 4.2 and 4.3 are independent of each other. 4.4 is gated on a
human decision, not on code. 4.5 should land last so it can reuse the harness
4.2/4.3 establish — 4.3 contributes the seeded-generation and condition-arm
pattern (a metric is only trusted once a control shows it separates).

**Exit criteria:**
- A CI run on a backend PR shows tests, lint and types green.
- Every pipeline stage has at least one reproducible eval with a committed result
  artifact.
- `REQ-EVL-02` is `Done`; `REQ-EVL-04` and `REQ-EVL-06` are `Done` —
  `REQ-EVL-06` ✅.
- The RAGAS decision is recorded — either implemented or explicitly deferred with
  the reasoning written down.

## Phase 5 — Ingestion breadth

**Goal:** more than PDFs, measured the same way.

| # | Requirement | Notes |
| --- | --- | --- |
| 5.1 | `REQ-EXT-04` | Non-PDF types (DOCX, HTML, plain text). Establishes the extractor seam that OCR and scraping then reuse. |
| 5.2 | `REQ-EXT-03` | OCR for scanned PDFs (Tesseract), with an eval comparing OCR'd against native extraction. |
| 5.3 | `REQ-EXT-05` | Web scraping ingestion. **Watch the data rule:** scraped content is never committed. |

**Dependencies:** all three need Phase 4's extraction eval to exist first —
otherwise there is no way to show a new source produces usable text. Order within
the phase is 5.1 → 5.2/5.3.

**Exit criteria:** each new source has an extraction eval showing chunk quality
comparable to the PDF path, and the README lists the supported types.

## Phase 6 — Access and governance

**Goal:** scope retrieval precisely per user, and validate what the model returns.

| # | Requirement | Notes |
| --- | --- | --- |
| 6.1 | `REQ-SEC-02` | Document categories and multi-role access — replaces the flat `access_role` column with the join table the schema already anticipates. Schema change: do it before the data grows. |
| 6.2 | `REQ-EMB-02` | Dimension-agnostic embedding storage. Bundled here because it's the other schema change, and doing both migrations at once is cheaper than two. |
| 6.3 | `REQ-SEC-03` | LLM output validation alongside the Pydantic schemas, with an eval measuring what it catches. |

**Dependencies:** 6.1 and 6.2 both migrate the schema — plan them as one
migration. 6.3 depends on Phase 4's faithfulness eval to have something to measure
against.

**Exit criteria:** a document can carry a category and several roles, retrieval
filters on both, an embedding model of a different dimension can be swapped in
without hand-written DDL, and a failing generated answer is caught rather than
returned.

## Phase 7 — More chunking strategies

**Goal:** widen the strategy set now that the measurement layer can judge it.

| # | Requirement | Notes |
| --- | --- | --- |
| 7.1 | `REQ-CHK-06` | Recursive chunking — cheap, deterministic, a natural second baseline. |
| 7.2 | `REQ-CHK-07` | LLM-based chunking. The only strategy that spends LLM calls at ingest, so it needs an explicit cost and latency note next to its scores. |

**Dependencies:** deliberately last. Adding strategies is easy; the value is in
being able to *tell* whether they're better, which Phase 4 provides.

**Exit criteria:** both are registered behind `Chunker`, scored by the comparison
eval on the same two datasets, and reported by `/process` like the rest — with the
comparison numbers committed.

---

## Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Local judge quality (`REQ-EVL-05`) | A small local model is a noisy grader; metrics could mislead more than they inform | Treat LLM-judged numbers as indicative, pin model and temperature, keep the deterministic embedding score as the ranking metric. **Reduced** — `REQ-EVL-06` ships a deterministic faithfulness measure, so a judge model is now an addition rather than the only route to grounding numbers |
| Faithfulness threshold is fitted (`REQ-EVL-06`) | `0.75` was calibrated on 8 questions over 2 documents with one embedding model; a different corpus or model could move it, quietly changing what "supported" means | The eval sweeps the threshold on every run and records it in the artifact, so drift is visible rather than silent; `mean_support` is threshold-free and is the number relied on |
| Generation is not bit-reproducible (`REQ-EVL-06`) | A seeded run still varies; a reader could treat one run's digits as fixed, or read normal noise as a regression | The eval's conclusion is the ordering across its three conditions, which has held on every run; the docstring, README and requirement evidence all say to read a single run as one sample |
| Eval runtime | Semantic chunking and any LLM-judged eval are slow; a slow eval stops being run | Keep evals offline and out of the request path; keep the fast test suite free of both |
| Schema coupling to 768 dims | Blocks embedding-model experiments (`REQ-EMB-02`) | Address in Phase 6 alongside the other migration |
| Backend gates are local-only (`REQ-QUA-06`) | A PR from another environment bypasses tests, lint and types entirely | **Closed** — the `backend-ci` workflow re-runs format, lint, types and the fast tests on every PR touching `backend/**` |
| Scraped and source data leaking into git (`REQ-SEC-04`) | Disclosure, and history rewriting to fix | gitleaks on staged diffs, gitignored data paths, human PII check before every commit |

## Working agreements

- **One requirement per branch, per PR.** Branches are `mh/<kebab-case-name>`.
- **No strategy or stage merges without its eval.** Comparative where possible:
  new against existing, same data, numbers recorded.
- **The README updates in the same change**, not after.
- **Stack-affecting changes run `deploy-verify` before the PR.**
- **Phase order is a default, not a rule.** Pulling something forward is fine —
  say why in the PR and move it here, so this file keeps matching reality.
