"""FastAPI service exposing a file-processing endpoint.

Run with:
    uv run uvicorn api:app --host 127.0.0.1 --port 9080
"""

from collections.abc import Iterator
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from dtos.requests import (
    AnswerRequest,
    FixedSizeChunkingRequest,
    PageExclusion,
    RetrievalRequest,
)
from dtos.responses import AnswerResponse, ProcessResponse, RetrievalResponse
from services.answering import Answering
from services.file_processing import FileProcessing
from services.generation import LLMClient, OllamaClient
from services.retrieval import Retrieval
from services.storage import PostgresStorage

app = FastAPI(title="RAG Assistant — File Processing")

file_processing = FileProcessing()
retrieval = Retrieval()
answering = Answering()


def get_storage() -> Iterator[PostgresStorage]:
    """Yield a storage handle for one request, closing its connection after.

    Connects using ``$DATABASE_URL`` (see :meth:`PostgresStorage.connect`). A new
    connection per request keeps things simple and thread-safe; tests override
    this dependency with a fake so they never touch a database.
    """
    storage = PostgresStorage.connect()
    try:
        yield storage
    finally:
        storage.close()


def _validation_detail(field: str, exc: ValidationError) -> list[dict[str, Any]]:
    """Build a 422 detail for a JSON-carrying form field.

    Each error's ``loc`` is prefixed with the form field name, so a caller can
    tell *which* field was malformed instead of getting a bare "Input should be
    an object". ``include_context=False`` keeps the raw ValueError from a
    validator (which is not JSON-serializable) out of the response body.
    """
    return [
        {**error, "loc": (field, *error["loc"])}
        for error in exc.errors(include_context=False)
    ]


def get_llm() -> LLMClient:
    """Provide the LLM client for a request (Ollama, from the ``$OLLAMA_*`` env).

    Tests override this dependency with a fake so they never call a real model.
    """
    return OllamaClient.from_env()


@app.post("/process", response_model=ProcessResponse)
async def process(
    file: UploadFile = File(...),
    name: str = Form(..., description="Name to store the document under."),
    access_role: str = Form(
        ..., description="Role permitted to access the stored document."
    ),
    chunk_size: int | None = Form(
        None,
        gt=0,
        description=(
            "Words per chunk for the fixed-size candidate (default 200). "
            "Other strategies pick their own boundaries."
        ),
    ),
    exclude_pages: str | None = Form(
        None,
        description=(
            "JSON array of pages to skip: page numbers and/or inclusive ranges "
            '(e.g. [1, {"start": 10, "end": 12}]). '
            "Optional, and applies to every chunking strategy."
        ),
    ),
    storage: PostgresStorage = Depends(get_storage),
) -> ProcessResponse:
    """Chunk a file every way, keep the best, and return the scores.

    The caller does not choose a chunking strategy. Every implemented strategy
    chunks the document, each is scored (cohesion vs separation), and only the
    winner's chunks are kept in the database. The response reports every
    strategy's evaluation and names the one that remains in ``chunking_strategy``.
    """
    fixed_request = (
        FixedSizeChunkingRequest(chunk_size=chunk_size)
        if chunk_size is not None
        else None
    )

    exclusion: PageExclusion | None = None
    if exclude_pages is not None:
        try:
            exclusion = PageExclusion.from_json_array(exclude_pages)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=_validation_detail("exclude_pages", exc)
            ) from exc

    content = await file.read()
    return file_processing.process(
        content,
        name,
        access_role,
        fixed_request,
        exclusion,
        filename=file.filename,
        content_type=file.content_type,
        storage=storage,
    )


@app.post("/retrieve", response_model=RetrievalResponse)
async def retrieve(
    request: RetrievalRequest,
    storage: PostgresStorage = Depends(get_storage),
) -> RetrievalResponse:
    """Embed the query and return the most similar stored chunks.

    Only chunks of documents with the request's ``access_role`` are searched.
    """
    return retrieval.retrieve(request, storage)


@app.post("/answer", response_model=AnswerResponse)
async def answer(
    request: AnswerRequest,
    storage: PostgresStorage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> AnswerResponse:
    """Retrieve context for the question and generate a grounded answer.

    Retrieves chunks of documents with the request's ``access_role``, passes them
    to the LLM as context, and returns the answer with those chunks as sources.
    """
    return answering.answer(request, storage, llm)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9080)
