---
name: record-change
description: >-
  Append an entry to .claude/Change-Log.md from merged work — what changed for a
  reader of the system, which requirement IDs it closed, and the eval numbers
  behind any improvement claim. Use after a merge to main, or when asked to write
  up, log, or document what shipped.
---

# Record a change

[Change-Log.md](../../Change-Log.md) records what changed **for someone using the
system** — not what changed in the diff. Write it so a reader who never saw the PR
understands what's different now.

## 1. Find what merged

```bash
git log --merges --pretty=format:'%h|%ad|%s' --date=short -5
```

Then read the actual work in the merge, not just the subject line:

```bash
git log <merge-sha>^1..<merge-sha> --stat
```

If several PRs merged on the same date, they share one dated entry, with all the
PR numbers on the trailing line — that's the existing convention in the file.

## 2. Map it to requirement IDs

Every entry names the requirement IDs it closes or advances. Check them against
[Requirements.md](../../Requirements.md).

**An entry with no ID is a finding, not a formatting problem.** It means work
shipped that no requirement asked for. Either the requirement is missing — run
`add-requirement` — or the work was out of scope. Say which, rather than quietly
writing the entry without an ID.

## 3. Draft the entry

Append under a date heading (merge date, newest first), with only the sections
that apply:

```markdown
## YYYY-MM-DD

### Added
- **Thing that now exists** (`REQ-XXX-NN`). What it does, and the behaviour that
  matters — the constraint, the default, the failure mode a user would hit.

### Changed
- **What's different now**, and what that enables or costs.

*PR #NN*
```

`### Added` / `### Changed` / `### Fixed` / `### Removed` — Keep a Changelog
sections, in that order.

## 4. Write it at the right altitude

The rule: **describe the system, not the source tree.**

| Weak | Strong |
| --- | --- |
| "Refactored `file_processing.py`" | "Decoupled evaluation from chunking, so a document can be re-scored with a new question set without re-chunking" |
| "Added `structural.py`" | "Structural chunking breaks on the markers a document already carries, so it needs no embeddings; a document with no markers falls back to paragraphs" |
| "Updated the model config" | "Generation defaults to `gemma2:2b` (~1.6 GB), comfortable on CPU-only hardware; `gpt-oss:20b` remains a one-variable swap" |

Include the details a reader would trip over: the default, the bound, the error
they'll get, the thing that's now deleted. The existing entries in the file set
the register — match them.

## 5. Cite the numbers

If the change claims something improved, **quote the eval output**. That's this
project's standard everywhere else and the changelog is not an exception. Read the
figures from `backend/evals/results/` — don't paraphrase from memory.

Good: *"Structural scores **−0.18** on the structured document against −0.31
(semantic) and −0.31 to −0.38 (fixed-size)."*

Not: *"Structural chunking performs better."*

If a change shipped without an eval and one was required, that's worth a line in
your report to the user — it means a requirement is `Partial`, not `Done`.

## 6. Keep the Unreleased section honest

The `## Unreleased` block at the top says what's merged but not yet released, or
what's next. After appending a dated entry, update it — either to name what's
still pending, or to point at the next phase in [Plan.md](../../Plan.md).

## 7. Then sync the status

```bash
/sync-status
```

The changelog records that something shipped; `sync-status` re-derives whether the
requirement it closed is genuinely `Done`. Run it every time — they're two halves
of the same update.
