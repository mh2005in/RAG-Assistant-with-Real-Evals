"""Answering service.

Everything behind the ``/answer`` endpoint: retrieve the most relevant chunks for
the question, build an augmented prompt from them (the RAG "augment" step), and
ask an LLM to answer grounded in that context. Route handlers stay thin and
delegate here (see CLAUDE.md).

Retrieval is delegated to the :class:`~services.retrieval.Retrieval` service and
generation to any :class:`~services.generation.LLMClient`, so this service only
orchestrates and owns the prompt.
"""

from dtos.requests import AnswerRequest, RetrievalRequest
from dtos.responses import AnswerResponse, RetrievedChunk
from services.generation import LLMClient
from services.retrieval import Retrieval
from services.storage import PostgresStorage

# Returned without calling the model when retrieval finds nothing to ground on --
# there is no context to answer from, so there is nothing to generate.
_NO_CONTEXT_ANSWER = "I couldn't find any relevant documents to answer that question."


class Answering:
    """Answer a question from retrieved context using an LLM.

    Pass a ``retrieval`` to override or inject a fake in tests; otherwise a default
    :class:`~services.retrieval.Retrieval` is used (its embedder loads lazily).
    """

    def __init__(self, retrieval: Retrieval | None = None) -> None:
        self._retrieval = retrieval or Retrieval()

    def answer(
        self, request: AnswerRequest, storage: PostgresStorage, llm: LLMClient
    ) -> AnswerResponse:
        """Retrieve context for the question and generate a grounded answer.

        When retrieval returns nothing, a fixed "no documents" answer is returned
        without calling the model.
        """
        retrieved = self._retrieval.retrieve(
            RetrievalRequest(
                query=request.query,
                access_role=request.access_role,
                top_k=request.top_k,
            ),
            storage,
        )
        if not retrieved.results:
            return AnswerResponse(
                query=request.query, answer=_NO_CONTEXT_ANSWER, sources=[]
            )

        prompt = self._build_prompt(request.query, retrieved.results)
        answer = llm.generate(prompt)
        return AnswerResponse(
            query=request.query, answer=answer, sources=retrieved.results
        )

    @staticmethod
    def _build_prompt(query: str, chunks: list[RetrievedChunk]) -> str:
        """Build the augmented prompt: the retrieved chunks as cited context.

        Each chunk is numbered and tagged with its document and page so the model
        can cite it (e.g. ``[1]``).
        """
        context = "\n".join(
            f"[{index}] ({chunk.document_name}, p.{chunk.page_number}) {chunk.text}"
            for index, chunk in enumerate(chunks, start=1)
        )
        return (
            "Answer the question using ONLY the context below. If the answer is "
            "not in the context, say you don't know. Cite the sources you use "
            "like [1].\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {query}\n"
            "Answer:"
        )
