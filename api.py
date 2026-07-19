"""FastAPI service exposing a file-processing endpoint.

Run with:
    uv run uvicorn api:app --host 127.0.0.1 --port 9080
"""

from collections.abc import Iterator

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from dtos.requests import (
    AnswerRequest,
    ChunkingStrategy,
    FixedSizeChunkingRequest,
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


def get_llm() -> LLMClient:
    """Provide the LLM client for a request (Ollama, from the ``$OLLAMA_*`` env).

    Tests override this dependency with a fake so they never call a real model.
    """
    return OllamaClient.from_env()


@app.post("/process", response_model=ProcessResponse)
async def process(
    file: UploadFile = File(...),
    strategy: ChunkingStrategy = Form(...),
    name: str = Form(..., description="Name to store the document under."),
    access_role: str = Form(
        ..., description="Role permitted to access the stored document."
    ),
    fixed_size: str | None = Form(
        None,
        description=(
            "JSON body of FixedSizeChunkingRequest "
            '(e.g. {"chunk_size": 512, "exclude_pages": [1, {"start": 10, "end": 12}]}). '
            "Required when strategy is 'fixed'."
        ),
    ),
    storage: PostgresStorage = Depends(get_storage),
) -> ProcessResponse:
    """Accept a file and chunking strategy; chunk, embed, and store it.

    When ``strategy`` is ``fixed``, ``fixed_size`` must contain the JSON body
    of a :class:`FixedSizeChunkingRequest`. Documents that produce chunks are
    persisted under ``name``/``access_role`` and their ``document_id`` is
    returned.
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
    return file_processing.process(
        content,
        strategy,
        name,
        access_role,
        fixed_request,
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
