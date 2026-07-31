"""File-processing service.

Everything behind the ``/process`` endpoint: detect the document type, extract its
text, chunk it with *every* implemented strategy, and embed and persist each chunk
the moment it is produced (so a document's chunks never all sit in memory at once).
Route handlers stay thin and delegate here (see CLAUDE.md).

Scoring is a *separate* stage: this service stores every strategy without judging
it, and ``/evaluate`` (see :class:`~services.evaluation.Evaluation`) compares them
after the fact and keeps the best. So chunking never pays the cost of scoring.

Chunking strategies stay behind the :class:`~services.chunking.Chunker` interface
rather than becoming methods here, so they can be run and compared
apples-to-apples.
"""

import pymupdf

from dtos.requests import ChunkingStrategy, FixedSizeChunkingRequest, PageExclusion
from dtos.responses import Chunk, DocType, ProcessResponse, StoredStrategy
from services.chunking import (
    Chunker,
    FixedSizeChunker,
    SemanticChunker,
)
from services.embedding import Embedder, OllamaEmbedder
from services.storage import PostgresStorage

_PDF_MAGIC = b"%PDF-"
# The %PDF- marker should sit at the very start, but some producers emit a few
# leading bytes; the spec tolerates it within the first chunk of the file.
_MAGIC_SEARCH_WINDOW = 1024

# Words per chunk for the fixed-size candidate when the caller does not tune it.
_DEFAULT_CHUNK_SIZE = 200


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

    @staticmethod
    def _exclude_pages(pages: list[str], exclusion: PageExclusion | None) -> list[str]:
        """Blank out the excluded pages, keeping every page's position.

        Excluded pages are emptied rather than dropped so the remaining pages keep
        their original 1-based numbers (chunkers read page N from index N-1) and
        chunks stay attributed to the right page. An emptied page contributes no
        text, so it is effectively excluded for any chunking strategy.
        """
        if exclusion is None:
            return pages
        excluded = exclusion.excluded_page_numbers()
        if not excluded:
            return pages
        return [
            "" if page_number in excluded else text
            for page_number, text in enumerate(pages, start=1)
        ]

    def _candidates(
        self, fixed_size: FixedSizeChunkingRequest
    ) -> dict[ChunkingStrategy, Chunker]:
        """The chunking strategies competing for this document."""
        return {
            ChunkingStrategy.fixed: FixedSizeChunker(fixed_size),
            ChunkingStrategy.semantic: SemanticChunker(self._get_embedder()),
        }

    def process(
        self,
        content: bytes,
        name: str,
        access_role: str,
        fixed_size: FixedSizeChunkingRequest | None = None,
        page_exclusion: PageExclusion | None = None,
        filename: str | None = None,
        content_type: str | None = None,
        storage: PostgresStorage | None = None,
    ) -> ProcessResponse:
        """Chunk the document every way, embedding and storing each chunk as made.

        The caller does not pick a strategy. Every implemented strategy chunks the
        same (page-excluded) text, and each chunk is embedded and persisted the
        moment it is produced — so only one chunk is held in memory at a time,
        instead of every strategy's chunks accumulating for a single batch write.
        All strategies' chunks land against one ``documents`` row. No strategy is
        scored or dropped here — that is ``/evaluate``'s job (see
        :class:`~services.evaluation.Evaluation`), so the same document can be
        scored later without re-chunking.

        ``fixed_size`` tunes the fixed-size candidate (defaulting to
        ``_DEFAULT_CHUNK_SIZE`` words); ``page_exclusion`` is strategy-agnostic and
        is applied before any chunking. The response reports which strategies were
        stored and their chunk counts.
        """
        doc_type = self._detect_doc_type(
            content, filename=filename, content_type=content_type
        )
        if doc_type is not DocType.pdf:
            return ProcessResponse(processed=len(content) > 0, doc_type=doc_type)

        pages = self._exclude_pages(self._extract_pdf_pages(content), page_exclusion)
        fixed_size = fixed_size or FixedSizeChunkingRequest(
            chunk_size=_DEFAULT_CHUNK_SIZE
        )

        # Chunk, embed and persist one chunk at a time, for every strategy. Each
        # chunk is stored the moment it is created and embedded, so only a single
        # chunk (and its vector) is ever held in memory — rather than every
        # strategy's chunks accumulating for one batch insert. None is dropped
        # here; /evaluate scores the strategies and prunes the losers later.
        embedder = self._get_embedder()
        document_id: int | None = None
        strategies: list[StoredStrategy] = []
        for strategy, chunker in self._candidates(fixed_size).items():
            chunk_count = 0
            for page, text in chunker.chunk_with_pages(pages):
                chunk = embedder.embed_chunks([Chunk.from_page(page, text)])[0]
                if storage is not None:
                    if document_id is None:
                        # Created on the first chunk, which also clears any chunks
                        # a previous run stored for this document.
                        document_id = storage.create_document(name, access_role)
                    storage.insert_chunk(
                        document_id, strategy.value, chunk_count, chunk
                    )
                chunk_count += 1
                # `chunk` (and its vector) is free to be collected next iteration.
            strategies.append(
                StoredStrategy(strategy=strategy.value, chunk_count=chunk_count)
            )

        # The response reports what was stored; the chunks themselves are read
        # back through /retrieve, and scored through /evaluate.
        return ProcessResponse(
            processed=True,
            doc_type=doc_type,
            document_id=document_id,
            strategies=strategies,
        )
