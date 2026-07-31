# CLAUDE.md

Guidance for working in this repository. Keep it short and current — prune rules that stop being true.

## Maintaining this guidance

- **Keep the automation current alongside the rules.** The hooks (`.claude/settings.json`, `.githooks/`), skills, and agents that back these rules are part of them — when behavior changes, update the hook/skill/agent in the same change, not just the prose. A rule that describes a hook must match what the hook actually does.
- **Before adding a rule here, decide whether it should be automation instead.** CLAUDE.md is for judgment Claude must apply while working. If a proposed rule is a mechanical every-time check (formatting, a naming/author gate, a scan), it's a **hook** candidate; a procedure that applies only to certain tasks is a **skill** candidate; delegated multi-step work is an **agent** candidate. When the user proposes a CLAUDE.md change, say which of these it fits, recommend the best home, and — once agreed — implement it there rather than defaulting to more always-on prose.

## Project

RAG assistant built with an **evaluation-driven** approach: every pipeline stage (extraction → web scraping → chunking → embedding → storage → validation) is measured with real evals, not vibes. See [README.md](README.md) for the stage-by-stage architecture. Early development — architecture and tooling are still being finalized.

**Repository layout:** the Python/RAG service lives in [`backend/`](backend/) (all app code, `pyproject.toml`/`uv.lock`, `Dockerfile`, `db/`); [`frontend/`](frontend/) is reserved for the web UI (not built yet). Docker Compose, `.env`/`.env.example`, this file, and the README stay at the repo root and span both. **Run all `uv`/Python commands from `backend/`** (`cd backend`, or `uv run --directory backend …`).

## Enforced automatically (don't re-check by hand)

- **Format, lint, type check** — `.claude/settings.json` hooks run `ruff format` + `ruff check --fix` after every edit and `mypy` at the end of each turn (all via `uv run --directory backend`, since the project lives there). Still fix anything they flag before calling work done.
- **Pre-commit gate** — the `.githooks/pre-commit` hook checks the author is `mh2005in`, runs `gitleaks` on staged changes, then runs the fast tests (`pytest -m "not integration"`, from `backend/`). gitleaks matches secret *patterns* only; **it does not catch PII** (real names, emails) — that's on you.
- **Worktree cleanup** — the `.githooks/post-merge` hook removes merged worktrees. See that file's header for exactly when it runs.
- **Post-deploy cleanup** — after the [`deploy-verify`](.claude/agents/deploy-verify.md) agent signals a clean pass (it writes `.claude/.deploy-verify-pass`), a `SubagentStop` hook (`.claude/hooks/deploy-verify-cleanup.sh`) removes build/verify leftovers: Python caches, dangling Docker images + build cache, the session scratchpad, and empty stray dirs. It's a no-op after any other subagent or a failed deploy, and never fails the turn.
- Enable the git hooks in a fresh clone: `git config core.hooksPath .githooks`.

## Tooling

- **Package/env manager: `uv`.** Never call `pip` or edit dependency versions by hand. Add deps with `uv add <pkg>` (dev: `uv add --dev`); run anything with `uv run <cmd>`. Run these from `backend/` — that's where `pyproject.toml`/`uv.lock` live. Commit both `backend/pyproject.toml` and `backend/uv.lock`.
- Target the single pinned Python version in `backend/pyproject.toml` (`requires-python`).

## Eval-driven workflow

- **A pipeline stage is not "done" until it has a real eval.** No new chunking/embedding/retrieval strategy merges without a measurement of how it performs.
- Prefer comparative evals: evaluate a new strategy against the existing ones on the same data, and record the numbers.
- Keep eval datasets, prompts, and results reproducible — check in the eval code and config; treat scores as regenerable artifacts, not screenshots.
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
- Don't delete or weaken a failing test to make the suite pass — fix the cause or ask.

## Local stack (Docker Compose)

- The app is packaged ([backend/Dockerfile](backend/Dockerfile), build context `./backend`) and runs as the `app` service in [docker-compose.yml](docker-compose.yml) alongside Postgres/pgvector and Ollama. Whole stack: `docker compose up -d --build` (from repo root; app on `http://localhost:8000`). Keep it runnable this way.
- **Wire new functionality into the stack in the same change:** new env var → add to the `app` service `environment:` and [.env.example](.env.example); new dependency (service/model) → add a compose service and wire `depends_on`/env. New Python deps are picked up by `uv sync` on the next `--build`.
- **Services talk by compose service name** over the internal network (`db:5432`, `ollama:11434`), not `localhost` or host ports. `DATABASE_URL` is built in compose — don't hardcode it.
- **After any change that could affect the deployable stack, verify it with the [`deploy-verify`](.claude/agents/deploy-verify.md) agent** — and again before a commit/PR that touches those. "Stack-affecting" means the `backend/Dockerfile`, `docker-compose.yml`, backend deps (`backend/pyproject.toml`/`uv.lock`), env config (`.env.example`), `backend/db/schema.sql`, or backend app code. The agent builds the stack, waits for the `rag-app`/`rag-postgres`/`rag-ollama` healthchecks, and exercises `/openapi.json` — real deploy + health, not just host-run tests. Docs- or test-only changes don't need it.

## Documentation

- **Keep [README.md](README.md) current in the same change**, not as a follow-up — for any new/changed endpoint, architecture/pipeline change, dependency/stack change, new config/env var, or setup/usage change.
- The README describes **what exists today**. Aspirational work goes under "Roadmap"; when it ships, move it out into the relevant section.
- Pure internals with no user-facing effect (small refactor, comment fix) don't need a README edit — but if in doubt, update it.

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
