#!/bin/sh
# SubagentStop cleanup hook.
#
# Fires after EVERY subagent, but only does work when the deploy-verify agent
# left its PASS marker (.claude/.deploy-verify-pass) -- the agent writes that
# marker only on a healthy deploy. So this is a no-op after any other subagent
# and after a failed deploy. It then removes build/verify leftovers and consumes
# the marker. It must never fail the turn, so every step is best-effort and the
# script always exits 0.
#
# Configured as a SubagentStop hook in .claude/settings.json. Runs with cwd at
# the repo root; the hook payload (JSON) arrives on stdin.

# Read the payload before anything else consumes stdin.
payload="$(cat 2>/dev/null || true)"

project_dir="$(pwd)"
marker="$project_dir/.claude/.deploy-verify-pass"

# --- Gate: only clean up after a clean deploy-verify pass ---
[ -f "$marker" ] || exit 0

# --- 1. Python tooling caches (repo-wide; skip venvs, .git, node_modules) ---
find "$project_dir" \
  \( -path '*/.git' -o -path '*/.venv' -o -name node_modules \) -prune -o \
  -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache \
             -o -name .ruff_cache \) -print 2>/dev/null \
  | while IFS= read -r d; do rm -rf "$d" 2>/dev/null || true; done

# --- 2. Dangling Docker images + build cache from the verify build ---
# Only dangling/untagged resources -- never named volumes (pgdata/ollama) or the
# tagged app image, and never the running stack.
if command -v docker >/dev/null 2>&1; then
  docker image prune -f >/dev/null 2>&1 || true
  docker builder prune -f >/dev/null 2>&1 || true
fi

# --- 3. Session scratchpad (best-effort, heavily guarded) ---
# Rebuild the scratchpad path from the session id (stdin) and the project slug,
# then empty it. Guard hard so a bad match can never delete anything unexpected.
sid="$(printf '%s' "$payload" \
  | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
if [ -n "$sid" ] && [ -n "$LOCALAPPDATA" ]; then
  base="$(cygpath -u "$LOCALAPPDATA" 2>/dev/null || printf '%s' "$LOCALAPPDATA")"
  winpath="$(cygpath -w "$project_dir" 2>/dev/null || printf '%s' "$project_dir")"
  slug="$(printf '%s' "$winpath" | sed 's#[:\\/]#-#g')"
  scratch="$base/Temp/claude/$slug/$sid/scratchpad"
  case "$scratch" in
    */claude/*/scratchpad)
      [ -d "$scratch" ] && find "$scratch" -mindepth 1 -delete 2>/dev/null || true
      ;;
  esac
fi

# --- 4. Stray leftover empty dirs (git can't track these; safe to prune) ---
find "$project_dir" \
  \( -path '*/.git' -o -path '*/.venv' -o -path '*/.claude' -o -name node_modules \) -prune -o \
  -type d -empty -print 2>/dev/null \
  | while IFS= read -r d; do rmdir "$d" 2>/dev/null || true; done

# --- Consume the marker so the next subagent doesn't re-trigger cleanup ---
rm -f "$marker" 2>/dev/null || true

exit 0
