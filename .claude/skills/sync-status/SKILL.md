---
name: sync-status
description: >-
  Re-derive .claude/Status-Dashboard.md and the requirement statuses from what is
  actually in the repository — tests, eval artifacts, hooks, CI, git state. Use
  after a merge, when the dashboard looks stale, or when someone asks where the
  project stands, what's left, or how much is done.
---

# Sync the status dashboard

[Status-Dashboard.md](../../Status-Dashboard.md) is **derived state**. Your job is
to regenerate it from evidence, not to edit numbers by hand. If a claim in the
dashboard disagrees with the repository, the repository is right.

## 1. Gather the facts

Run these and use the real output — never carry a number over from the previous
version of the file:

```bash
cd backend && uv run pytest --collect-only -q -m "not integration" | tail -2
```

```bash
cd backend && uv run pytest --collect-only -q -m "integration" | tail -2
```

Also collect:

- **Git state** — current branch, HEAD short SHA, the most recent merge commit
  and its date, and anything uncommitted or untracked (`git status --short`).
- **Eval artifacts** — every file in `backend/evals/results/`, its scores, and
  whether the eval that produces it still exists in `backend/evals/`.
- **Frontend specs** — counts in `frontend/e2e/mocked/`, `frontend/e2e/stack/`,
  and the component specs under `frontend/src/`.
- **Gates** — the hooks in `.claude/settings.json`, `.githooks/`, and the
  workflows in `.github/workflows/`. What's automated, and what only exists as a
  convention.
- **Stack** — the services in `docker-compose.yml` and their healthchecks.

## 2. Re-derive every requirement status

For each row in [Requirements.md](../../Requirements.md), check whether the
evidence column points at something that **exists right now** and actually
supports the claim. Delegate the audit to the **`requirements-analyst`** agent —
it reads the code, tests and eval artifacts and reports what the evidence
supports.

Apply the rules strictly:

- **`Done`** needs evidence that exists and demonstrably meets the acceptance
  criterion. A path that no longer exists demotes the requirement immediately.
- **Pipeline stages** (`EXT`/`CHK`/`EMB`/`STO`/`RET`/`GEN`) additionally need a
  real eval with a committed result artifact. Code plus tests is **not** enough —
  that's `Partial`.
- **`Partial`** must name the specific gap. "Mostly working" is not a gap.
- **`Proposed`** means blocked on a decision. Name the decision and say it's
  outstanding.

Update any status that changed, and record **why** it changed in your report.

## 3. Rewrite the dashboard

Regenerate every section of [Status-Dashboard.md](../../Status-Dashboard.md):

- **Header** — today's date, branch, HEAD SHA, last merge and its date.
- **At a glance** — phase position, requirement counts by status, delivered
  percentage, test counts, gate coverage, working-tree state.
- **Requirements by stage** — the bar chart and the per-stage table. Keep the bars
  consistent with the counts; recompute both.
- **Where the risk actually is** — the honest read. Lead with the weakest area,
  not the most complete one. Name blocked decisions and unguarded gaps.
- **Current eval numbers** — read them from `backend/evals/results/`, don't
  transcribe from the old file. Keep the caveats that still apply and drop the
  ones that don't.
- **Gate status** — automated / on-demand / human-check / missing.
- **Next actions** — the earliest open phase in [Plan.md](../../Plan.md), in
  order, with the reasoning for the order.
- **Housekeeping** — untracked files, stale worktrees, dangling artifacts.

Recompute the traceability summary at the bottom of Requirements.md too, so the
two files agree.

## 4. Report what changed

Summarise for the user:

- Statuses that moved, each with the evidence that moved it
- Counts before and after
- Anything newly at risk — a demoted requirement, a missing artifact, a gate that
  stopped running
- Whether the next action from the plan has changed

## Guardrails

**Don't inflate.** A requirement is not `Done` because the code looks finished.
It's `Done` when the evidence exists and the acceptance criterion is met. This
project's premise is that things are measured rather than asserted — the dashboard
is the one place that's most tempting to fudge, and the least useful if fudged.

**Don't hide a regression.** If evidence disappeared or an eval result got worse,
that's the most important line in the report. Lead with it.

**Don't invent numbers.** Every figure comes from a command you ran or a file you
read. If something can't be measured right now (the stack isn't up, an eval needs
Ollama), say so and mark it unknown rather than reusing a stale value.
