"""File-processing service.

Everything behind the ``/process`` endpoint: detect the document type, extract
its text, and chunk it with the requested strategy. Route handlers stay thin and
delegate here (see CLAUDE.md).

Chunking strategies stay behind the :class:`~services.chunking.Chunker`
interface rather than becoming methods here, so evals can compare them
apples-to-apples.
"""

import pymupdf

from dtos.requests import ChunkingStrategy, FixedSizeChunkingRequest
from dtos.responses import Chunk, DocType, ProcessResponse
from services.chunking import FixedSizeChunker
from services.embedding import Embedder, OllamaEmbedder
from services.storage import PostgresStorage

_PDF_MAGIC = b"%PDF-"
# The %PDF- marker should sit at the very start, but some producers emit a few
# leading bytes; the spec tolerates it within the first chunk of the file.
_MAGIC_SEARCH_WINDOW = 1024


class FileProcessing:
    """Detect, extract, chunk and embed uploaded files for ``/process``.

    The embedder loads its model lazily on first use, so constructing the
    service (and importing the app) stays cheap and offline until a document is
    actually embedded. Pass an ``embedder`` to override the model/device or to
    inject a fake in tests.
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = OllamaEmbedder.from_env()
        return self._embedder

    def _detect_doc_type(
        self,
        content: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> DocType:
        """Identify the document type of ``content``.

        Content sniffing (the leading ``%PDF-`` marker) takes precedence. The
        ``filename`` extension and declared ``content_type`` are used only when
        the bytes are inconclusive, so a mislabelled file is still classified by
        its actual contents.
        """
        if _PDF_MAGIC in content[:_MAGIC_SEARCH_WINDOW]:
            return DocType.pdf
        if content_type and "pdf" in content_type.lower():
            return DocType.pdf
        if filename and filename.lower().endswith(".pdf"):
            return DocType.pdf
        return DocType.unknown

    def _extract_pdf_pages(self, content: bytes) -> list[str]:
        """Extract text from a PDF, one entry per page (page 1 at index 0).

        Raises :class:`ValueError` if ``content`` is not a readable PDF.
        """
        try:
            with pymupdf.open(stream=content, filetype="pdf") as doc:
                return [page.get_text() for page in doc]
        except Exception as exc:  # PyMuPDF surfaces several error types
            raise ValueError("content is not a readable PDF") from exc

    def process(
        self,
        content: bytes,
        strategy: ChunkingStrategy,
        name: str,
        access_role: str,
        fixed_size: FixedSizeChunkingRequest | None = None,
        filename: str | None = None,
        content_type: str | None = None,
        storage: PostgresStorage | None = None,
    ) -> ProcessResponse:
        """Detect the document type, chunk it, and (if given) persist it.

        ``fixed_size`` carries the fixed-size chunking parameters and is required
        when ``strategy`` is :attr:`ChunkingStrategy.fixed`.

        When chunks are produced and a ``storage`` is supplied, the document is
        saved under ``name``/``access_role`` with its chunks, and the new
        document id is returned on the response. The full (un-truncated) chunks
        are persisted; only the response copies are clipped.

        Currently only PDFs chunked with the fixed-size strategy produce chunks;
        each response chunk carries its per-page stats plus a clipped preview of
        its text and embedding (the full payloads are only used internally). Other
        document types and strategies are detected/accepted but return no chunks
        yet (they are wired in as the pipeline matures).
        """
        if strategy is ChunkingStrategy.fixed and fixed_size is None:
            raise ValueError(
                "fixed_size parameters are required for the 'fixed' strategy"
            )

        doc_type = self._detect_doc_type(
            content, filename=filename, content_type=content_type
        )

        if doc_type is DocType.pdf and strategy is ChunkingStrategy.fixed:
            assert fixed_size is not None  # guaranteed by the guard above
            pages = self._extract_pdf_pages(content)
            paged = FixedSizeChunker(fixed_size).chunk_with_pages(pages)
            chunks = [Chunk.from_page(page_number, text) for page_number, text in paged]
            document_id: int | None = None
            if chunks:
                chunks = self._get_embedder().embed_chunks(chunks)
                # Persist the full chunks (full text + vector) before the response
                # copies are clipped below.
                if storage is not None:
                    document_id = storage.insert_document(
                        name, access_role, chunks
                    ).document_id
            # Clip the bulky text/embedding payloads so the response stays small;
            # the per-page stats still describe the full page and vector.
            return ProcessResponse(
                processed=True,
                doc_type=doc_type,
                chunk_count=len(chunks),
                chunks=[chunk.truncated() for chunk in chunks],
                document_id=document_id,
            )

        return ProcessResponse(processed=len(content) > 0, doc_type=doc_type)
