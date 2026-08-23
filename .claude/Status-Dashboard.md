# Status Dashboard

**As of 2026-08-23** · branch `main` at `203abac` · last merge PR #30
(delivery-document rule, 2026-08-23)

Derived state — do not hand-edit. Refresh with the `sync-status` skill, which
re-reads the repository and rewrites this file. Every number below traces to
something in the repo; where it doesn't, it says so.

---

## At a glance

| | |
| --- | --- |
| **Phase** | 3 of 7 complete · **Phase 4 (Measurement depth) in progress** — 4.1 shipped, 4.2–4.5 open |
| **Requirements** | 38 Done · 4 Partial · 10 Planned · 1 Proposed — **53 total** |
| **Delivered** | 71% of the register (38/53) |
| **Backend tests** | 143 collected — 137 fast/offline, 6 `integration` |
| **Frontend tests** | 9 mocked E2E specs · 3 stack E2E specs · 2 component specs |
| **Quality gates** | **7 of 7 requirements met** — backend CI closed the last gap |
| **Stack** | 4 services + one-shot model puller, all healthchecked |
| **Working tree** | Clean except untracked `.idea/misc.xml` |

## Requirements by stage

```
EXT  ███░░░░░░░░░░░░  1/5    CHK  ██████████░░░░░  5/7
EMB  ███████░░░░░░░░  1/2    STO  ███████████████  3/3
RET  ███████░░░░░░░░  1/2    GEN  ███████░░░░░░░░  1/2
EVL  █████░░░░░░░░░░  2/6    API  ███████████████  4/4
SEC  ███████░░░░░░░░  2/4    UI   ███████████████  4/4
OPS  ███████████████  4/4    QUA  ███████████████  7/7
DOC  ███████████████  3/3
```

| Stage | Done | Open | State |
| --- | --- | --- | --- |
| Storage, API, UI, Ops, Docs | 18 | 0 | **Complete** |
| Quality | 7 | 0 | **Complete** — backend CI closed the last gap on 2026-08-23 |
| Chunking | 5 | 2 | Three strategies shipped; recursive and LLM-based deferred to Phase 7 |
| Retrieval | 1 | 1 | Works; the per-strategy filter is unproven at the `/retrieve` and `/answer` layer |
| Generation | 1 | 1 | Works; *grounded* is a quality claim with no eval behind it yet |
| Extraction | 1 | 4 | PDF only; page exclusion unproven for two of three strategies |
| Access & safety | 2 | 2 | Flat role works; richer roles and output validation in Phase 6 |
| Embedding | 1 | 1 | Works; locked to 768 dims by the schema |
| **Evaluation** | 2 | 4 | **The thinnest area, and the project's whole premise** |

## Where the risk actually is

**Evaluation coverage is the weak point.** `REQ-EVL-02` — every stage measured by
a real eval — is the requirement the project's premise rests on, and an audit on
2026-08-23 found it casts a longer shadow than the register admitted. Today:

| Stage | Eval? |
| --- | --- |
| Chunking | ✅ Two: a fixed-size sweep and a three-strategy comparison, both with committed artifacts |
| Retrieval | ⚠️ Only indirectly, through `/evaluate` at request time — no offline eval |
| Generation | ❌ None. `/answer` quality is currently unmeasured |
| Extraction, Embedding, Storage | ❌ None |

All four open evaluation requirements (`REQ-EVL-02`, `04`, `05`, `06`) are the
remainder of Phase 4 — which is why Phase 4 continues rather than the more visible
feature work in Phases 5–7.

**Three requirements were demoted on 2026-08-23** by an evidence audit, and they
are the honest reading of what is actually proven:

| Requirement | Why it is `Partial` |
| --- | --- |
| `REQ-GEN-01` | *"Returns a **grounded** answer"* is a quality claim. The response shape is tested; groundedness is not measured. `REQ-EVL-06` is the eval that would close it. |
| `REQ-RET-02` | Every `RetrievalRequest`/`AnswerRequest` in the suite omits `chunking_strategy`, so the filter is proven only at the storage layer — never through `/retrieve` or `/answer`, which is what the criterion states. |
| `REQ-EXT-02` | Page exclusion is asserted only for the `fixed` strategy; nothing checks semantic or structural chunks, so the criterion's **every strategy** clause is unproven. |

The last two are **test-coverage gaps, not eval gaps** — each closes with a test,
not a measurement campaign.

**One decision is blocking work.** `REQ-EVL-05` (RAGAS LLM-judge) can't start
until someone chooses: a fully-local judge — open-source and free, but a small
model is a noisy grader — or an external judge API, stronger but with per-call
cost. The project's stated stance favours local. Until it's recorded, the
requirement stays `Proposed`.

**The eval datasets are too small to settle anything.** 273 and 556 words. Every
number in the next section carries that caveat.

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
| Backend format / lint / types / fast tests | CI, on `backend/**` PRs | ✅ Automated |
| Stack deploy + health + stack E2E | `deploy-verify` agent, on request | ⚙️ On demand |
| Post-deploy cleanup | After a clean `deploy-verify` (hook) | ✅ Automated |
| Merged-worktree cleanup | On merge into `main` (hook) | ✅ Automated |
| **PII in staged diffs** | — | 👤 **Human check — gitleaks matches secret patterns only** |

Nine gates are automated, one runs on request, and one stays a human
responsibility. Local hooks and CI now cover the same ground, so a contributor
without `core.hooksPath` configured is no longer unguarded.

## Next actions

In order, from [Plan.md](Plan.md) Phase 4. Item 4.1 (`REQ-QUA-06`) shipped on
2026-08-23; what remains:

1. **Decide `REQ-EVL-05`** — local judge vs external judge API. A decision, not
   code; it unblocks the deepest eval work.
2. **`REQ-EVL-04`** — rank-aware metrics (recall@k, MRR, nDCG) over the Q&A set
   `/evaluate` already takes. Report alongside existing metrics; don't change
   ranking behaviour in the same change.
3. **`REQ-EVL-06`** — answer-faithfulness eval, the first coverage of the
   generation stage.
4. **`REQ-EVL-02`** — retrieval and embedding evals, plus larger eval datasets, to
   close stage coverage and flip this to `Done`.

## Housekeeping

- `.idea/misc.xml` is untracked while the rest of `.idea/` **is** tracked (7
  files). It should either be committed or added to `.gitignore` — decide, rather
  than leaving it dangling.
- `.claude/worktrees/` is not in `.gitignore`, so an active worktree shows as
  untracked content in the main checkout.
- One active worktree (`changelog-sync`); the merged ones were removed
  automatically by the `post-merge` hook.

## Refreshing this file

```bash
# From the repo root, in Claude Code:
/sync-status
```

`sync-status` re-derives every status from evidence, recomputes the counts and
tables, and reports what changed and why. Run it after any merge. If a number here
disagrees with the repository, the repository is right and this file is stale.
