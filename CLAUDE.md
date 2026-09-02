# CLAUDE.md

Guidance for working in this repository. Keep it short and current — prune rules that stop being true.

## Maintaining this guidance

- **Keep the automation current alongside the rules.** The hooks (`.claude/settings.json`, `.githooks/`), skills, and agents that back these rules are part of them — when behavior changes, update the hook/skill/agent in the same change, not just the prose. A rule that describes a hook must match what the hook actually does.
- **Before adding a rule here, decide whether it should be automation instead.** CLAUDE.md is for judgment Claude must apply while working. If a proposed rule is a mechanical every-time check (formatting, a naming/author gate, a scan), it's a **hook** candidate; a procedure that applies only to certain tasks is a **skill** candidate; delegated multi-step work is an **agent** candidate. When the user proposes a CLAUDE.md change, say which of these it fits, recommend the best home, and — once agreed — implement it there rather than defaulting to more always-on prose.

## Project

RAG assistant built with an **evaluation-driven** approach: every pipeline stage (extraction → web scraping → chunking → embedding → storage → validation) is measured with real evals, not vibes. See [README.md](README.md) for the stage-by-stage architecture. Early development — architecture and tooling are still being finalized.

**Repository layout:** the Python/RAG service lives in [`backend/`](backend/) (all app code, `pyproject.toml`/`uv.lock`, `Dockerfile`, `db/`); the Angular web UI lives in [`frontend/`](frontend/). Docker Compose, `.env`/`.env.example`, this file, and the README stay at the repo root and span both. **Run all `uv`/Python commands from `backend/`** (`cd backend`, or `uv run --directory backend …`).

## Delivery documents ([`.claude/`](.claude/))

Requirements, plan and status live in the repo, not in someone's head. Keep them current with the code — the same rule the README follows.

- **[Requirements.md](.claude/Requirements.md)** — the register: every requirement has a stable `REQ-<STAGE>-<NN>` id, a *testable* acceptance criterion, a status, and the evidence that proves it. Nothing gets built without an id.
- **[Plan.md](.claude/Plan.md)** — phases and sequencing for everything not yet done, with dependencies and exit criteria. Pull work from the earliest open phase.
- **[Architecture.md](.claude/Architecture.md)** — boundaries, contracts, data model, request flows, and the decision record. Update it when a boundary or trade-off changes.
- **[Delivery-Approach.md](.claude/Delivery-Approach.md)** — the delivery loop, the Definition of Done, and how the skills and agents fit together. This is the contract the automation implements.
- **[Status-Dashboard.md](.claude/Status-Dashboard.md)** — derived state. Don't hand-edit; regenerate with `/sync-status`.
- **[Change-Log.md](.claude/Change-Log.md)** — what shipped, by merge date, naming the requirement ids it closed.

**Statuses are derived from evidence, not declared.** A pipeline-stage requirement that makes a **quality** claim can't reach `Done` without a real eval — same rule as [Eval-driven workflow](#eval-driven-workflow) below. A functional contract in the same stage (a status code, a schema constraint, a config swap) is proven by tests instead.

### Skills and agents

Four skills drive the loop; four agents do the delegated work inside it.

| Skill | Use it when |
| --- | --- |
| [`deliver-requirement`](.claude/skills/deliver-requirement/SKILL.md) | Building anything with a REQ id — runs the whole loop and stops at each failing gate |
| [`add-requirement`](.claude/skills/add-requirement/SKILL.md) | A new need appears, or a requirement turns out to be untestable |
| [`sync-status`](.claude/skills/sync-status/SKILL.md) | After a merge, or when asked where the project stands |
| [`record-change`](.claude/skills/record-change/SKILL.md) | After a merge, to log what shipped |

| Agent | Delegated job |
| --- | --- |
| [`requirements-analyst`](.claude/agents/requirements-analyst.md) | Audits whether a requirement's evidence supports its status (read-only) |
| [`eval-runner`](.claude/agents/eval-runner.md) | Runs the evals and test tiers, reports numbers and regressions |
| [`docs-sync`](.claude/agents/docs-sync.md) | Cross-checks README, this file and `.claude/` docs against the repo (read-only) |
| [`deploy-verify`](.claude/agents/deploy-verify.md) | Builds the stack, waits for health, exercises the API and stack E2E |

## Enforced automatically (don't re-check by hand)

- **Format, lint, type check** — `.claude/settings.json` hooks run `ruff format` + `ruff check --fix` after every edit and `mypy` at the end of each turn (all via `uv run --directory backend`, since the project lives there). Still fix anything they flag before calling work done.
- **Pre-commit gate** — the `.githooks/pre-commit` hook checks the author is `mh2005in`, runs `gitleaks` on staged changes, then runs the fast tests (`pytest -m "not integration"`, from `backend/`). gitleaks matches secret *patterns* only; **it does not catch PII** (real names, emails) — that's on you.
- **CI on pull requests** — [`backend-ci.yml`](.github/workflows/backend-ci.yml) re-runs the backend gates (`ruff format --check`, `ruff check`, `mypy`, fast `pytest`) on any PR touching `backend/**`; [`frontend-e2e.yml`](.github/workflows/frontend-e2e.yml) runs the mocked Playwright suite on any PR touching `frontend/**`. Same gates as the local hooks — CI is the backstop for an environment where the hooks aren't configured, so a red run means fix the cause, not re-run it.
- **Worktree cleanup** — the `.githooks/post-merge` hook removes merged worktrees. See that file's header for exactly when it runs.
- **Post-deploy cleanup** — after the [`deploy-verify`](.claude/agents/deploy-verify.md) agent signals a clean pass (it writes `.claude/.deploy-verify-pass`), a `SubagentStop` hook (`.claude/hooks/deploy-verify-cleanup.sh`) removes build/verify leftovers: Python caches, dangling Docker images + build cache, the session scratchpad, and empty stray dirs. It's a no-op after any other subagent or a failed deploy, and never fails the turn.
- Enable the git hooks in a fresh clone: `git config core.hooksPath .githooks`.

## Tooling

- **Package/env manager: `uv`.** Never call `pip` or edit dependency versions by hand. Add deps with `uv add <pkg>` (dev: `uv add --dev`); run anything with `uv run <cmd>`. Run these from `backend/` — that's where `pyproject.toml`/`uv.lock` live. Commit both `backend/pyproject.toml` and `backend/uv.lock`.
- Target the single pinned Python version in `backend/pyproject.toml` (`requires-python`).

## Eval-driven workflow

- **A pipeline stage's quality claims are not "done" until they have a real eval.** No new chunking/embedding/retrieval strategy merges without a measurement of how it performs. This gates claims about *how well* something works — not the stage's functional contracts, which tests prove.
- Prefer comparative evals: evaluate a new strategy against the existing ones on the same data, and record the numbers.
- **A new eval carries a control arm** — an arrangement that must score badly (shuffled text, a random vector, a distractor context). A metric that cannot fail is not measuring anything, and a run where the control scores like a real arm is a broken metric, not a good result. The extraction, embedding, storage and generation evals have one; the chunking and retrieval evals predate the rule and compare real candidates only, so their metrics rest on argument rather than on a demonstrated floor.
- Keep eval datasets, prompts, and results reproducible — check in the eval code and config; treat scores as regenerable artifacts, not screenshots. Every stage has an eval today (see the [`eval-runner`](.claude/agents/eval-runner.md) table); a new extractor, strategy or model joins its stage's eval as another arm in the same change.
- Evals run offline against the checked-in fixtures, but most of them embed text and so need a running Ollama — only [`extraction_fidelity_eval.py`](backend/evals/extraction_fidelity_eval.py) and the fixed-size sweep need nothing. [`storage_index_eval.py`](backend/evals/storage_index_eval.py) additionally needs a live Postgres, because it measures the HNSW index and a stand-in for a database cannot be approximate the way the real one is.
- When you claim something "works" or "improved," cite the eval output — don't assert quality from reading code.

## Code style & structure

- Validate structured inputs/outputs with **Pydantic** models, not raw dicts across module boundaries.
- **Keep request/response DTOs in separate folders** under `backend/dtos/` (`backend/dtos/requests/`, `backend/dtos/responses/`). Don't define them inline in `backend/api.py` or route modules; import them.
- **Put processing logic in `backend/services/`, not route handlers.** Search `backend/services/` for an existing implementation before writing a new one; reuse or extract-and-share rather than duplicate. Route handlers stay thin and delegate.
- **One service class per endpoint — don't over-modularize.** Each processing step is a method on that class, not a module per step (e.g. everything behind `/process` lives on `FileProcessing` in `backend/services/file_processing.py`). Only split into a new service once a second endpoint needs it.
- **Use the narrowest access a method allows.** Mark internals with a single leading underscore; keep a class's public surface to what callers actually use (`FileProcessing` exposes only `process()`). Same for module-level helpers/constants. Widen to public only for a real external caller.
- Organize by pipeline stage; keep each stage's strategies swappable behind a common interface so evals compare apples-to-apples.
- Match surrounding style; don't add a second way to do something that already has a pattern.

## Testing

- **pytest** (`uv run pytest`, from `backend/`). Write tests alongside the code they cover; a bug fix comes with a test that fails without it.
- Keep unit tests fast and offline — mock external services (LLM APIs, Firecrawl, DB). Tests needing Postgres/pgvector or network go behind `@pytest.mark.integration` so the default run stays fast.
- **Frontend E2E: Playwright** (specs in `frontend/e2e/`, run from `frontend/`). Same fast-vs-integration split as pytest: `npm run e2e` is the default — offline, the four API endpoints stubbed in-browser with `page.route()`, no backend needed (run in CI on frontend changes). `npm run e2e:stack` runs against the live Compose stack (nginx + FastAPI) for what only the deployment proves (SPA deep-link fallback, the proxy hop) — the integration tier, run by the [`deploy-verify`](.claude/agents/deploy-verify.md) agent, not on every change. Angular component unit specs stay under `ng test` (karma). Prefer role/label selectors; add a `data-testid` only when disambiguation needs it.
- Don't delete or weaken a failing test to make the suite pass — fix the cause or ask.

## Local stack (Docker Compose)

- The app is packaged ([backend/Dockerfile](backend/Dockerfile), build context `./backend`) and runs as the `app` service in [docker-compose.yml](docker-compose.yml) alongside the `frontend` (nginx serving the Angular SPA, [frontend/Dockerfile](frontend/Dockerfile), context `./frontend`), Postgres/pgvector, and Ollama. Whole stack: `docker compose up -d --build` (from repo root; frontend on `http://localhost:4200`, app on `http://localhost:8000`). Keep it runnable this way.
- **Wire new functionality into the stack in the same change:** new env var → add to the relevant service `environment:` and [.env.example](.env.example); new dependency (service/model) → add a compose service and wire `depends_on`/env. New Python deps are picked up by `uv sync` on the next `--build`. New backend endpoint the UI should call → also add its path to the frontend proxy ([frontend/nginx.conf](frontend/nginx.conf) and [frontend/proxy.conf.json](frontend/proxy.conf.json)).
- **Services talk by compose service name** over the internal network (frontend → `app:8000`; app → `db:5432`, `ollama:11434`), not `localhost` or host ports. `DATABASE_URL` is built in compose — don't hardcode it. The frontend is same-origin with the API (nginx proxies it), so no CORS config is needed.
- **After any change that could affect the deployable stack, verify it with the [`deploy-verify`](.claude/agents/deploy-verify.md) agent** — and again before a commit/PR that touches those. "Stack-affecting" means the `backend/Dockerfile` or `frontend/Dockerfile`, `frontend/nginx.conf`, `docker-compose.yml`, backend deps (`backend/pyproject.toml`/`uv.lock`), env config (`.env.example`), `backend/db/schema.sql`, or backend/frontend app code. The agent builds the stack, waits for the `rag-frontend`/`rag-app`/`rag-postgres`/`rag-ollama` healthchecks, and exercises `/openapi.json` plus the frontend `/` — real deploy + health, not just host-run tests. Docs- or test-only changes don't need it.

## Documentation

- **Keep [README.md](README.md) current in the same change**, not as a follow-up — for any new/changed endpoint, architecture/pipeline change, dependency/stack change, new config/env var, or setup/usage change.
- The README describes **what exists today**. Aspirational work goes under "Roadmap"; when it ships, move it out into the relevant section.
- Pure internals with no user-facing effect (small refactor, comment fix) don't need a README edit — but if in doubt, update it.
- **The [`.claude/`](.claude/) delivery documents are documentation too** — update them in the same change, not as a follow-up. Which ones a change touches is a judgment call: [Requirements.md](.claude/Requirements.md) when a requirement's evidence or acceptance criterion moves, [Plan.md](.claude/Plan.md) when a phase's contents or sequencing change or a risk it lists is closed, [Architecture.md](.claude/Architecture.md) when a boundary or trade-off changes, [Delivery-Approach.md](.claude/Delivery-Approach.md) when the loop or the automation behind it changes. Don't leave one stale because it wasn't the file you were editing.
- **Hunt down prose that asserts the gap you just closed.** A "known gap" note, a risk row or a rationale sentence elsewhere will still claim the thing is missing. Grep the requirement id and a phrase from the gap across `README.md`, `CLAUDE.md` and `.claude/*.md` before calling a change done.
- [Status-Dashboard.md](.claude/Status-Dashboard.md) and [Change-Log.md](.claude/Change-Log.md) are the exceptions — derived state and post-merge, regenerated by `/sync-status` and `/record-change`. Don't hand-edit them.

## Secrets, PII & data handling

- **Replace secrets and PII with placeholders before committing.** Real API keys / DB credentials → `YOUR_API_KEY_HERE`; real names/emails/phones/addresses/IDs or a real user's document contents → obvious fakes (`Jane Doe`, `user@example.com`, `+1-555-0100`). Prefer synthetic fixtures over redacting real data. Scan the staged diff before every commit — gitleaks catches secrets, **not** PII.
- A committed secret is compromised: rotate the key, don't just amend. Committed PII is a disclosure: purge it from history and tell whoever owns the data.
- **Never commit source documents, scraped content, embeddings, or DB dumps** — `.gitignore` them, keep them out of the repo. Postgres/pgvector details come from config/env, never hardcoded.

## Git

- Don't commit or push unless asked. Keep commits focused (hooks handle format/lint/type/secret gates).
- **Author commits and PRs as `mh2005in`.** If git's configured author is anything else, stop and fix the config first.
- **Do not add Claude as author/co-author** — no `Co-Authored-By: Claude` trailer, no Claude attribution or CLAUDE.md reference in commit messages or PR bodies.
- **Temp/working branches: `mh/<kebab-case-name>`.** Never put "claude" (or any agent name) in the branch name.

## Worktrees

- Feature work happens in `.claude/worktrees/<name>/`. On a verified PR merge to `main`, remove that worktree (`git worktree remove …`) and prune its branch (`git branch -d …`) — the `.githooks/post-merge` hook does this automatically when you pull merged work into `main`.
- Only remove a worktree after the merge is verified — never one with unmerged/uncommitted work. Don't delete the `main` checkout or the shared root `CLAUDE.md`.
