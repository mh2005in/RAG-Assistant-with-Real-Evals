---
name: deliver-requirement
description: >-
  Take one requirement from .claude/Requirements.md through the full delivery
  loop — verify, branch, implement, test, eval, document, deploy-verify, PR,
  changelog, status. Use when starting or continuing work on a REQ id (e.g.
  "REQ-QUA-06", "let's do the backend CI requirement", "build the next thing
  from the plan"). Also use when asked to work on something that should have a
  requirement but doesn't yet — it routes to add-requirement first.
---

# Deliver a requirement

You are running the delivery loop from
[Delivery-Approach.md](../../Delivery-Approach.md). Work one requirement at a
time, and stop at any gate that fails rather than working around it.

## 0. Resolve the requirement

- Given a REQ id, read its row in [Requirements.md](../../Requirements.md).
- Given a description with no id, search the register for a match. If nothing
  matches, **stop and run `add-requirement` first** — nothing gets built without
  an id.
- If it's already `Done`, say so and ask what changed before reopening it.
- If it's `Proposed`, it's blocked on a decision. Surface the decision to the
  user and stop — don't decide it yourself.

Check [Plan.md](../../Plan.md): if this requirement isn't in the earliest open
phase, say so and confirm before proceeding. Pulling work forward is allowed, but
it's a choice, not an accident.

## 1. Confirm the acceptance criterion is testable

Read the acceptance criterion aloud in your plan. If you can't name the concrete
check that proves it — a test, an eval number, an HTTP response, a healthcheck —
the requirement is not ready. Fix it with `add-requirement`, then come back.

Delegate the evidence audit to the **`requirements-analyst`** agent: it reports
what the current evidence actually supports, which tells you what's genuinely
left to build versus what already exists.

## 2. Branch into a worktree

Feature work happens in `.claude/worktrees/<name>/` on a `mh/<kebab-case-name>`
branch. Never put an agent name in the branch. Never work directly on `main`.

## 3. Implement

Follow [CLAUDE.md](../../../CLAUDE.md) — it wins over anything here:

- Pydantic models for structured input/output across module boundaries; request
  and response DTOs in `backend/dtos/requests/` and `backend/dtos/responses/`,
  never inline in a route.
- Processing logic in `backend/services/`. **Search `backend/services/` for an
  existing implementation before writing a new one** — reuse or extract-and-share
  rather than duplicate.
- One service class per endpoint; each step a method, not a module. Narrowest
  access a method allows; single leading underscore for internals.
- New strategies go behind the existing interface (`Chunker`, `Embedder`,
  `LLMClient`) so evals compare apples to apples.
- Match the surrounding style. Don't add a second way to do something that
  already has a pattern.
- Run `uv` commands from `backend/`. Never call `pip`, never hand-edit versions.

## 4. Test alongside

- `uv run pytest` from `backend/`. Fast and offline by default — mock the LLM
  API, Firecrawl and the DB.
- Anything needing Postgres/pgvector or the network goes behind
  `@pytest.mark.integration`.
- A bug fix ships with a test that fails without it.
- Frontend changes: Playwright specs in `frontend/e2e/` (mocked tier by default),
  component specs under `ng test`. Prefer role/label selectors; add a
  `data-testid` only when disambiguation needs it.
- **Never delete or weaken a failing test to get green.** Fix the cause or ask.

## 5. Eval the stage — the step that must not be skipped

If the requirement touches a pipeline stage (`EXT`, `CHK`, `EMB`, `STO`, `RET`,
`GEN`), it isn't done without a real eval:

- **Comparative**: the new strategy against the existing ones, same data, one
  variable changed.
- **Reproducible**: eval code and config checked in under `backend/evals/`;
  results are regenerable artifacts in `backend/evals/results/`, never
  screenshots.
- Run it through the **`eval-runner`** agent and quote its numbers.

When you claim something works or improved, **cite the eval output**. Don't assert
quality from reading code.

## 6. Update the documentation in the same change

Not as a follow-up:

- [README.md](../../../README.md) — any new or changed endpoint, architecture or
  pipeline change, dependency or stack change, new config/env var, or setup
  change. Shipped work moves out of Roadmap into the relevant section.
- [Architecture.md](../../Architecture.md) — if a boundary, contract, data model
  or decision changed. Add a decision-record row when you made a real trade-off.
- Pure internals with no user-facing effect don't need a README edit — but if in
  doubt, update it.

## 7. Wire it into the stack

If the change adds anything the deployed stack needs:

- New env var → the relevant service `environment:` **and**
  [.env.example](../../../.env.example).
- New service or model → a compose service, with `depends_on` and env wired.
- New backend endpoint the UI should call → add its path to **both**
  [nginx.conf](../../../frontend/nginx.conf) and
  [proxy.conf.json](../../../frontend/proxy.conf.json).
- Services talk by compose service name, never `localhost` or a hardcoded URL.

## 8. Verify the deploy

If the change touches either Dockerfile, `frontend/nginx.conf`,
`docker-compose.yml`, backend deps, `.env.example`, `backend/db/schema.sql`, or
backend/frontend app code — run the **`deploy-verify`** agent. Docs-only or
test-only changes skip it.

A FAIL stops the loop. Fix the cause and re-run; don't proceed with a broken
stack.

## 9. Check for documentation drift

Run the **`docs-sync`** agent. It cross-checks the README, CLAUDE.md and the
`.claude/` documents against the repository and against each other. Fix whatever
it reports before the PR.

## 10. Commit and PR

Only when the user asks to commit or push.

- Author as `mh2005in`. If git's configured author is anything else, **stop and
  fix the config first**.
- **No Claude attribution** — no `Co-Authored-By: Claude` trailer, no agent name,
  no CLAUDE.md reference in the message or PR body.
- Keep the commit focused; the hooks handle format, lint, type and secret gates.
- **Scan the staged diff for PII yourself** — gitleaks matches secret patterns
  only. Real names, emails, phones, addresses, IDs, or a real user's document
  contents get replaced with obvious fakes.

## 11. After the merge

1. `/record-change` — append the changelog entry naming the REQ ids closed.
2. `/sync-status` — re-derive the dashboard and the requirement statuses.
3. The post-merge hook removes the worktree when you pull the merge into `main`.
   Only remove a worktree after the merge is verified, never one with unmerged or
   uncommitted work.

## Definition of Done

Don't report the requirement complete until every line holds:

- [ ] Acceptance criterion observably met
- [ ] Tests in the right tier, passing
- [ ] Pipeline stage has a real eval with a committed result artifact
- [ ] `ruff format`, `ruff check`, `mypy` clean
- [ ] README reflects it, and it's out of Roadmap
- [ ] `deploy-verify` passed, if stack-affecting
- [ ] Requirements.md evidence points at something that exists
- [ ] Changelog entry recorded
- [ ] No secret, PII, source document, scraped content, embedding or DB dump committed

If something is genuinely blocked, finish everything else, mark the requirement
`Partial` with the gap written down, and say plainly what's left and why. "Nearly
done" is not a status.
