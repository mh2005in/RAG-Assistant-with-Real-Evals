---
name: add-requirement
description: >-
  Capture a new requirement in .claude/Requirements.md with a stable ID, a
  testable acceptance criterion, and a place in the plan — or correct an existing
  one. Use when someone proposes a feature, capability, constraint or gap ("we
  should also support X", "it needs to handle Y", "add a requirement for Z"), or
  when a requirement's wording turns out to be untestable or wrong.
---

# Add or correct a requirement

A requirement you can't test is a wish. Your job is to turn a proposal into a row
that [Requirements.md](../../Requirements.md) can actually hold, or to fix one
that isn't holding up.

## 1. Decide whether it's a requirement at all

Route it before you write it:

| The proposal is… | Where it goes |
| --- | --- |
| A capability, constraint or quality bar the system must meet | **A requirement** — continue below |
| A mechanical every-time check (format, lint, scan, gate) | A **hook** — `.claude/settings.json` or `.githooks/` |
| A procedure for a particular kind of task | A **skill** — `.claude/skills/` |
| Delegated multi-step work with its own context | An **agent** — `.claude/agents/` |
| A judgment call to apply while working | **CLAUDE.md** prose |
| How or when existing requirements get built | [Plan.md](../../Plan.md), not here |

Say which one it is and recommend the best home before implementing. This mirrors
the routing rule in [CLAUDE.md](../../../CLAUDE.md) — don't default to more
always-on prose.

## 2. Check it isn't already there

Search [Requirements.md](../../Requirements.md) for the same idea under different
words. Overlapping requirements are worse than missing ones: two rows drift, and
neither gets evidence. If it's close to an existing one, **amend that row** rather
than adding a second.

Also check the README's Roadmap and the phases in Plan.md — the idea may already
be captured, just not as a requirement.

## 3. Assign the ID

Format: `REQ-<STAGE>-<NN>`, where the stage prefix is the pipeline stage or
concern it belongs to:

`EXT` extraction · `CHK` chunking · `EMB` embedding · `STO` storage ·
`RET` retrieval · `GEN` generation · `EVL` evaluation · `API` service surface ·
`SEC` access and safety · `UI` frontend · `OPS` stack and config ·
`QUA` quality gates · `DOC` documentation

Take the **next unused number** in that stage. **Never renumber existing IDs** —
they're referenced from the changelog, the plan and commit messages. To drop a
requirement, mark it retired with the reason; don't delete the row and don't
reuse its number.

## 4. Write a testable acceptance criterion

This is the part that matters. The criterion names the observable condition that
makes the requirement `Done` — something a test, an eval number, an HTTP response,
or a healthcheck can confirm.

Reject vagueness. Rewrite it:

| Not a criterion | A criterion |
| --- | --- |
| "Retrieval should be fast" | "A top-5 retrieval over 10k chunks returns in under 200 ms, measured by the retrieval eval" |
| "Better chunking" | "Scores above the fixed-size baseline on the cohesion/separation eval for both sample datasets, with the artifact committed" |
| "Handle errors gracefully" | "A malformed `structural` field returns a 422 whose `loc` names the field" |
| "Support more formats" | "`POST /process` accepts a DOCX and reports `doc_type: \"docx\"`; chunks are retrievable afterwards" |

If the proposer can't say what would prove it, that's the finding — surface it
rather than writing a criterion you know can't be checked.

**For pipeline stages** (`EXT`/`CHK`/`EMB`/`STO`/`RET`/`GEN`), the criterion must
include a real eval. That's the project's rule, not a preference: no new chunking,
embedding or retrieval strategy is `Done` without a measurement of how it
performs, preferably comparative against what exists.

## 5. Set the status honestly

- `Planned` — agreed, not built. The normal starting state.
- `Proposed` — needs a **decision** before any code. Name the decision and who
  makes it. Don't decide it yourself.
- `Partial` — partly built. List the specific gap.
- `Done` — only with evidence that exists right now. Verify with the
  **`requirements-analyst`** agent before claiming it.

Evidence column: a real path for anything built, `—` for anything not. Never point
at a file that doesn't exist yet.

## 6. Place it in the plan

Add it to a phase in [Plan.md](../../Plan.md) with its dependencies, and say why
that phase. If it belongs before something already planned, move it and explain —
the sequencing rationale at the top of Plan.md is the argument to check it
against.

If it's urgent enough to jump the queue, say so explicitly rather than quietly
reordering.

## 7. Update the surrounding numbers

- Recompute the traceability summary at the bottom of Requirements.md.
- Run `/sync-status` so the dashboard reflects the new count.
- If the requirement describes user-facing behaviour that doesn't exist yet, it
  belongs in the README's **Roadmap** — not in the body, which describes what
  exists today.

## Correcting an existing requirement

Same steps, but keep the ID. Say in your summary what changed and why — a
requirement that silently changes meaning invalidates every claim of evidence made
against the old wording. If the change makes existing evidence insufficient, drop
the status from `Done` to `Partial` and note the gap.
