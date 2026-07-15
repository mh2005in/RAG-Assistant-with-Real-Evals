"""FastAPI service exposing a file-processing endpoint.

Run with:
    uv run uvicorn api:app --host 127.0.0.1 --port 9080
"""

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from dtos.requests import ChunkingStrategy, FixedSizeChunkingRequest
from dtos.responses import ProcessResponse
from services.file_processing import process_file

app = FastAPI(title="RAG Assistant — File Processing")


@app.post("/process", response_model=ProcessResponse)
async def process(
    file: UploadFile = File(...),
    strategy: ChunkingStrategy = Form(...),
    fixed_size: str | None = Form(
        None,
        description=(
            "JSON body of FixedSizeChunkingRequest "
            '(e.g. {"chunk_size": 512, "exclude_pages": [1, {"start": 10, "end": 12}]}). '
            "Required when strategy is 'fixed'."
        ),
    ),
) -> ProcessResponse:
    """Accept a file and chunking strategy; return whether it was processed.

    When ``strategy`` is ``fixed``, ``fixed_size`` must contain the JSON body
    of a :class:`FixedSizeChunkingRequest`.
    """
    fixed_request: FixedSizeChunkingRequest | None = None
    if strategy is ChunkingStrategy.fixed:
        if fixed_size is None:
            raise HTTPException(
                status_code=422,
                detail="fixed_size is required when strategy is 'fixed'.",
            )
        try:
            fixed_request = FixedSizeChunkingRequest.model_validate_json(fixed_size)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

    content = await file.read()
    return ProcessResponse(processed=process_file(content, strategy, fixed_request))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9080)
