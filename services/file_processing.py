"""File-processing service.

Everything behind the ``/process`` endpoint: detect the document type, extract its
text, chunk it with *every* implemented strategy, score them, and keep only the
best. Route handlers stay thin and delegate here (see CLAUDE.md).

Chunking strategies stay behind the :class:`~services.chunking.Chunker` interface
rather than becoming methods here, so they can be run and compared
apples-to-apples.
"""

import pymupdf

from dtos.requests import ChunkingStrategy, FixedSizeChunkingRequest, PageExclusion
from dtos.responses import Chunk, DocType, ProcessResponse, StrategyEvaluation
from services.chunking import (
    Chunker,
    FixedSizeChunker,
    SemanticChunker,
    score_chunks,
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

    def _evaluate(
        self, chunks_by_strategy: dict[str, list[Chunk]]
    ) -> list[StrategyEvaluation]:
        """Score each strategy's chunks, best first.

        Scoring is label-free (cohesion vs separation, see
        :func:`~services.chunking.score_chunks`), so it works on whatever document
        was just uploaded. The highest score is marked ``selected``.
        """
        embedder = self._get_embedder()
        scored: list[StrategyEvaluation] = []
        for strategy, chunks in chunks_by_strategy.items():
            texts = [chunk.text for chunk in chunks]
            cohesion, separation, score = score_chunks(texts, embedder)
            word_counts = [len(text.split()) for text in texts]
            scored.append(
                StrategyEvaluation(
                    strategy=strategy,
                    chunk_count=len(chunks),
                    mean_chunk_words=(
                        round(sum(word_counts) / len(word_counts), 2)
                        if word_counts
                        else 0.0
                    ),
                    cohesion=round(cohesion, 4),
                    separation=round(separation, 4),
                    score=round(score, 4),
                    selected=False,
                )
            )

        scored.sort(key=lambda evaluation: evaluation.score, reverse=True)
        if scored:
            scored[0] = scored[0].model_copy(update={"selected": True})
        return scored

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
        """Chunk the document every way, keep the best, and report the scores.

        The caller does not pick a strategy. Every implemented strategy chunks the
        same (page-excluded) text, all of their chunks are embedded and stored
        against one ``documents`` row, then each is scored and the losers' chunks
        are deleted — so exactly one strategy remains in the database.

        ``fixed_size`` tunes the fixed-size candidate (defaulting to
        ``_DEFAULT_CHUNK_SIZE`` words); ``page_exclusion`` is strategy-agnostic and
        is applied before any chunking. The response carries every strategy's
        evaluation and names the winner in ``chunking_strategy``.
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

        # Chunk and embed with every strategy. Embedding happens per strategy
        # because the chunk texts differ.
        embedder = self._get_embedder()
        chunks_by_strategy: dict[str, list[Chunk]] = {}
        for strategy, chunker in self._candidates(fixed_size).items():
            paged = chunker.chunk_with_pages(pages)
            chunks = [Chunk.from_page(page, text) for page, text in paged]
            if chunks:
                chunks = embedder.embed_chunks(chunks)
            chunks_by_strategy[strategy.value] = chunks

        if not any(chunks_by_strategy.values()):
            return ProcessResponse(processed=True, doc_type=doc_type)

        evaluations = self._evaluate(chunks_by_strategy)
        winner = next(item.strategy for item in evaluations if item.selected)

        document_id: int | None = None
        if storage is not None:
            # Store every candidate, then drop all but the winner, so the database
            # ends up holding exactly one strategy's chunks.
            document_id = storage.insert_document(
                name, access_role, chunks_by_strategy
            ).document_id
            storage.delete_chunks_except(document_id, winner)

        kept = chunks_by_strategy[winner]
        return ProcessResponse(
            processed=True,
            doc_type=doc_type,
            document_id=document_id,
            chunking_strategy=winner,
            evaluations=evaluations,
            chunk_count=len(kept),
            chunks=[chunk.truncated() for chunk in kept],
        )
