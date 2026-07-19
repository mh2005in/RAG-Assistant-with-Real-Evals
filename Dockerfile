# Package the FastAPI app for the docker-compose stack. Uses uv for a
# reproducible, lockfile-pinned install (see CLAUDE.md).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Install dependencies first, in their own layer, so this cache survives source
# changes. --no-install-project: install deps only (the app runs from source, it
# is not a packaged library). --no-dev: runtime deps only.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy the application source (see .dockerignore for what is left out).
COPY . .

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Readiness check: the app is up once it serves its OpenAPI schema.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/openapi.json')"

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
