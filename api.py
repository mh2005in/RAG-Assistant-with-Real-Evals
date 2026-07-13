"""FastAPI service exposing a file-processing endpoint.

Run with:
    uv run uvicorn api:app --host 127.0.0.1 --port 9080
"""

from enum import Enum

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

app = FastAPI(title="RAG Assistant — File Processing")


class ChunkingStrategy(str, Enum):
    """Chunking strategies under evaluation (see README)."""

    fixed = "fixed"
    semantic = "semantic"
    structural = "structural"
    recursive = "recursive"
    llm = "llm"


class ProcessResponse(BaseModel):
    processed: bool


def process_file(content: bytes, strategy: ChunkingStrategy) -> bool:
    """Process an uploaded file with the given chunking strategy.

    Returns True when processing succeeds. Currently this validates that the
    file has content; real chunking logic is wired in as the pipeline matures.
    """
    return len(content) > 0


@app.post("/process", response_model=ProcessResponse)
async def process(
    file: UploadFile = File(...),
    strategy: ChunkingStrategy = Form(...),
) -> ProcessResponse:
    """Accept a file and chunking strategy; return whether it was processed."""
    content = await file.read()
    return ProcessResponse(processed=process_file(content, strategy))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9080)
