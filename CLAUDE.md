# CLAUDE.md

Guidance for working in this repository. Keep it short and current — prune rules that stop being true.

## Project

RAG assistant built with an **evaluation-driven** approach: every pipeline stage (extraction → web scraping → chunking → embedding → storage → validation) is measured with real evals, not vibes. See [README.md](README.md) for the stage-by-stage architecture.

Early development — architecture and tooling are still being finalized.

## Tooling

- **Package/env manager: `uv`.** Never call `pip` or edit dependency versions by hand.
  - Add deps: `uv add <pkg>` (dev-only: `uv add --dev <pkg>`).
  - Run anything: `uv run <cmd>` (e.g. `uv run pytest`, `uv run python -m ...`).
  - Dependencies live in `pyproject.toml`; the lockfile is `uv.lock` — commit both.
- Target a single pinned Python version (declared in `pyproject.toml` `requires-python`).

## Eval-driven workflow

- **A pipeline stage is not "done" until it has a real eval.** No merging a new chunking/embedding/retrieval strategy without a measurement that shows how it performs.
- Prefer comparative evals: when adding a strategy (e.g. a new chunking method), evaluate it against the existing ones on the same data, and record the numbers.
- Keep eval datasets, prompts, and results reproducible — check in the eval code and config; treat scores as artifacts you can regenerate, not one-off screenshots.
- When you claim something "works" or "improved," cite the eval output. Don't assert quality from reading code alone.

## Code style & structure

- Format and lint with **Ruff** (`uv run ruff format .` and `uv run ruff check .`). Fix lint before considering work complete.
- **Type hints on all public functions**; run type checking (e.g. `uv run mypy` or `uv run pyright`) and keep it clean.
- Validate structured inputs/outputs with **Pydantic** models rather than passing raw dicts across module boundaries.
- **Keep request and response DTOs in separate folders** under `dtos/` (request DTOs → `dtos/requests/`, response DTOs → `dtos/responses/`). Don't define request/response models inline in `api.py` or route modules; import them from `dtos/`.
- **Put servicing/processing logic in `services/`, not in route handlers.** Before writing a new processing method, search `services/` for an existing implementation; if one exists, reuse it. If similar logic is duplicated across places, extract it into a common service in `services/` and import it everywhere. Route handlers in `api.py` should stay thin and delegate to services.
- **Don't over-modularize `services/` — one service class per endpoint.** Logic serving a single endpoint belongs in one service class, not a module per step. Give the endpoint one class in `services/<name>.py` and make each processing step a method on it — e.g. everything behind `/process` (doc-type detection, text extraction, chunking) belongs on the `FileProcessing` class in `services/file_processing.py`. Only split logic into its own service once a second endpoint actually needs it.
- **Use the narrowest access a method allows.** Python has no access modifiers, so mark internals with a single leading underscore. A method that nothing outside its own class calls is private (`_do_thing`); keep a class's public surface to what callers actually use. E.g. `FileProcessing` exposes only `process()` — detection and extraction are `_detect_doc_type()` / `_extract_pdf_pages()`. The same goes for module-level helpers and constants. Widen a method to public only when a real caller outside the class needs it.
- Organize code by pipeline stage. Keep each stage's strategies swappable behind a common interface so evals can compare them apples-to-apples.
- Match the style of surrounding code; don't introduce a second way to do something that already has a pattern.

## Testing

- Test framework: **pytest** (`uv run pytest`).
- Write tests alongside the code they cover; a bug fix should come with a test that fails without it.
- Keep unit tests fast and offline — mock external services (LLM APIs, Firecrawl, the database). Tests that need Postgres/pgvector or network belong behind a marker (e.g. `@pytest.mark.integration`) so the default run stays fast.
- Don't delete or weaken a failing test to make the suite pass — fix the underlying issue or ask.

## Secrets & data handling

- **Replace secrets with placeholders before committing.** Real API keys (Firecrawl, LLM providers) and DB credentials must be swapped for placeholder values (e.g. `YOUR_API_KEY_HERE`) in any file being committed — never commit a live secret.
  - Before every commit, scan the staged diff for real credentials and confirm they've been placeholdered.
  - If a real secret is ever committed, treat it as compromised: rotate the key, don't just amend the commit.
- **A pre-commit secret scanner (gitleaks) runs automatically** ([.githooks/pre-commit](.githooks/pre-commit) runs `gitleaks git --staged`). It blocks commits whose staged changes contain likely secrets.
  - Requires gitleaks to be installed. Windows: `winget install gitleaks` (or `scoop install gitleaks` / `choco install gitleaks`); macOS: `brew install gitleaks`. See https://github.com/gitleaks/gitleaks#installing.
  - Enable the hook in a fresh clone: `git config core.hooksPath .githooks` (config is per-clone, so each checkout must run this once).
  - It's a safety net, not a substitute for the placeholder rule above. Bypass a genuine false positive with `git commit --no-verify`.
- **Never commit source documents, scraped content, embeddings, or database dumps.** These are data artifacts — keep them out of git (add to `.gitignore`) and out of the repo.
- Don't paste real credentials, customer data, or scraped PII into code, tests, logs, or commit messages.
- PostgreSQL + pgvector connection details come from config/env, never hardcoded.

## Git

- Don't commit or push unless asked.
- Keep commits focused; run format, lint, type check, and tests before committing.
- **Author commits and PRs as `mh2005in`.** If git's configured author is anything else, stop and fix the config before committing — don't author under another identity.
- **Do not add Claude as an author or co-author.** No `Co-Authored-By: Claude` trailer and no Claude attribution in commit messages or PR bodies. Don't reference Claude/CLAUDE.md in commit messages either.
- **Temp/working branches: `mh/<work-related-name>`.** Prefix with `mh/`, then a short kebab-case description of the work. Do **not** put "claude" (or any agent name) in the branch name.

## Worktrees

- Feature work happens in git worktrees under `.claude/worktrees/<name>/`.
- **On a successful PR merge to `main`, delete that PR's worktree directory.** Once the merge is confirmed (e.g. `gh pr view <n> --json state,mergedAt` shows it merged), run `git worktree remove .claude/worktrees/<name>` from the main checkout to remove it cleanly (add `--force` only if the tree has intended leftover files). Then prune the merged branch with `git branch -d <branch>`.
- Only remove a worktree after the merge is verified — never delete one with unmerged or uncommitted work. Don't delete the `main` checkout or the shared root `CLAUDE.md`.
