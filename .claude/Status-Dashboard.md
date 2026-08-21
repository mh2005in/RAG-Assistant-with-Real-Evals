# Status Dashboard

**As of 2026-08-21** · branch `main` at `456f75c` · last merge PR #27
(structural chunking, 2026-08-16)

Derived state — do not hand-edit. Refresh with the `sync-status` skill, which
re-reads the repository and rewrites this file. Every number below traces to
something in the repo; where it doesn't, it says so.

---

## At a glance

| | |
| --- | --- |
| **Phase** | 3 of 7 complete · **Phase 4 (Measurement depth) is next, not started** |
| **Requirements** | 40 Done · 1 Partial · 11 Planned · 1 Proposed — **53 total** |
| **Delivered** | 75% of the register (40/53) |
| **Backend tests** | 143 collected — 137 fast/offline, 6 `integration` |
| **Frontend tests** | 9 mocked E2E specs · 3 stack E2E specs · 2 component specs |
| **Quality gates** | 6 of 7 automated — **backend CI missing** (`REQ-QUA-06`) |
| **Stack** | 4 services + one-shot model puller, all healthchecked |
| **Working tree** | Clean except untracked `.idea/misc.xml` |

## Requirements by stage

```
EXT  ██████░░░░░░░░░  2/5    CHK  ██████████░░░░░  5/7
EMB  ███████░░░░░░░░  1/2    STO  ███████████████  3/3
RET  ███████████████  2/2    GEN  ███████████████  2/2
EVL  █████░░░░░░░░░░  2/6    API  ███████████████  4/4
SEC  ███████░░░░░░░░  2/4    UI   ███████████████  4/4
OPS  ███████████████  4/4    QUA  ████████████░░░  6/7
DOC  ███████████████  3/3
```

| Stage | Done | Open | State |
| --- | --- | --- | --- |
| Storage, Retrieval, Generation, API, UI, Ops, Docs | 22 | 0 | **Complete** |
| Chunking | 5 | 2 | Three strategies shipped; recursive and LLM-based deferred to Phase 7 |
| Quality | 6 | 1 | One real gap — backend CI |
| Extraction | 2 | 3 | PDF only; OCR, other formats, scraping all Phase 5 |
| Access & safety | 2 | 2 | Flat role works; richer roles and output validation in Phase 6 |
| Embedding | 1 | 1 | Works; locked to 768 dims by the schema |
| **Evaluation** | 2 | 4 | **The thinnest area, and the project's whole premise** |

## Where the risk actually is

**Evaluation coverage is the weak point.** `REQ-EVL-02` — every stage measured by
a real eval — is the only `Partial` in the register, and it's the requirement the
project's premise rests on. Today:

| Stage | Eval? |
| --- | --- |
| Chunking | ✅ Two: a fixed-size sweep and a three-strategy comparison, both with committed artifacts |
| Retrieval | ⚠️ Only indirectly, through `/evaluate` at request time — no offline eval |
| Generation | ❌ None. `/answer` quality is currently unmeasured |
| Extraction, Embedding, Storage | ❌ None |

Four of the six open evaluation requirements (`REQ-EVL-02`, `04`, `05`, `06`) are
Phase 4 — which is why Phase 4 is next rather than the more visible feature work
in Phases 5–7.

**Backend CI is missing** (`REQ-QUA-06`). Tests, lint and types run as local hooks
only. A PR raised from an environment without `core.hooksPath` set is completely
unguarded. Small fix, first item of Phase 4.

**One decision is blocking work.** `REQ-EVL-05` (RAGAS LLM-judge) can't start
until someone chooses: a fully-local judge — open-source and free, but a small
model is a noisy grader — or an external judge API, stronger but with per-call
cost. The project's stated stance favours local. Until it's recorded, the
requirement stays `Proposed`.

## Current eval numbers

From [`chunking_strategies.json`](../backend/evals/results/chunking_strategies.json),
embedding model `nomic-embed-text`. Score is `cohesion − separation`, **higher is
better**.

**`structured_sample.txt`** — 556 words, carries its own section markers:

| Strategy | Chunks | Cohesion | Separation | **Score** |
| --- | --- | --- | --- | --- |
| **structural** | 11 | 0.5525 | 0.7346 | **−0.1821** ✅ best |
| semantic | 3 | 0.5391 | 0.8478 | −0.3086 |
| fixed (64) | 9 | 0.5164 | 0.8217 | −0.3053 |
| fixed (128) | 5 | 0.5137 | 0.8602 | −0.3466 |
| fixed (256) | 3 | 0.5072 | 0.8882 | −0.3810 |

Structural wins clearly here — most internally coherent *and* most distinct from
its neighbours. This is the result that justified shipping it.

**`sample.txt`** — 273 words, flat prose with no markers:

| Strategy | Chunks | Cohesion | Separation | **Score** |
| --- | --- | --- | --- | --- |
| fixed (256) | 2 | 0.7912 | 0.6876 | **+0.1036** |
| fixed (128) | 3 | 0.7115 | 0.8053 | −0.0938 |
| fixed (64) | 5 | 0.6460 | 0.7862 | −0.1401 |
| semantic | 2 | 0.5957 | 0.8000 | −0.2043 |
| structural | 4 | 0.6116 | 0.8198 | −0.2082 |

With nothing to find, structural falls back to paragraphs and lands with the rest —
a structure-aware strategy is only as good as the structure it's given.

> **Caveat worth carrying:** fixed-256 tops the flat table, but it produces **2
> chunks from a 273-word document**, so separation is averaged over a single
> adjacent pair. That's a small-sample artifact, not evidence that a 256-word
> window is the best strategy for flat prose. The datasets are 273 and 556 words —
> too small to settle anything. Larger datasets are part of finishing
> `REQ-EVL-02`.

## Gate status

| Gate | Runs | State |
| --- | --- | --- |
| `ruff format` + `ruff check --fix` | After every edit (hook) | ✅ Automated |
| `mypy` | End of every turn (hook) | ✅ Automated |
| Author is `mh2005in` | On commit (hook) | ✅ Automated |
| `gitleaks` on staged diff | On commit (hook) | ✅ Automated |
| Fast pytest (137 tests) | On commit (hook) | ✅ Automated |
| Mocked frontend E2E | CI, on `frontend/**` PRs | ✅ Automated |
| **Backend tests / lint / types in CI** | — | ❌ **Missing — `REQ-QUA-06`** |
| Stack deploy + health + stack E2E | `deploy-verify` agent, on request | ⚙️ On demand |
| Post-deploy cleanup | After a clean `deploy-verify` (hook) | ✅ Automated |
| Merged-worktree cleanup | On merge into `main` (hook) | ✅ Automated |
| **PII in staged diffs** | — | 👤 **Human check — gitleaks matches secret patterns only** |

## Next actions

In order, from [Plan.md](Plan.md) Phase 4:

1. **`REQ-QUA-06`** — backend CI workflow (fast tests, `ruff check`, `mypy` on
   `backend/**`). Smallest item, largest safety gain, no dependencies.
2. **Decide `REQ-EVL-05`** — local judge vs external judge API. A decision, not
   code; it unblocks the deepest eval work.
3. **`REQ-EVL-04`** — rank-aware metrics (recall@k, MRR, nDCG) over the Q&A set
   `/evaluate` already takes. Report alongside existing metrics; don't change
   ranking behaviour in the same change.
4. **`REQ-EVL-06`** — answer-faithfulness eval, the first coverage of the
   generation stage.
5. **`REQ-EVL-02`** — retrieval and embedding evals, plus larger eval datasets, to
   close stage coverage and flip this to `Done`.

## Housekeeping

- `.idea/misc.xml` is untracked. PyCharm config is tracked in this repo (see
  `7391bd9`), so it should either be committed or added to `.gitignore` — decide,
  rather than leaving it dangling.

## Refreshing this file

```bash
# From the repo root, in Claude Code:
/sync-status
```

`sync-status` re-derives every status from evidence, recomputes the counts and
tables, and reports what changed and why. Run it after any merge. If a number here
disagrees with the repository, the repository is right and this file is stale.
