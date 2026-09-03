"""File-processing service.

Everything behind the ``/process`` endpoint: detect the document type, extract its
text, chunk it with *every* implemented strategy, and embed and persist each chunk
the moment it is produced (so a document's chunks never all sit in memory at once).
Route handlers stay thin and delegate here (see CLAUDE.md).

Detecting the type is this service's job; reading it is not. Each format has an
extractor behind the :class:`~services.extraction.Extractor` interface (PDF, DOCX,
HTML, plain text), so a new source is added there rather than here. Only a PDF has
real pages — the rest extract to a single page, which is what their per-page stats
then describe.

Scoring is a *separate* stage: this service stores every strategy without judging
it, and ``/evaluate`` (see :class:`~services.evaluation.Evaluation`) compares them
after the fact and keeps the best. So chunking never pays the cost of scoring.

Chunking strategies stay behind the :class:`~services.chunking.Chunker` interface
rather than becoming methods here, so they can be run and compared
apples-to-apples.
"""

import zipfile
from io import BytesIO

from dtos.requests import (
    ChunkingStrategy,
    FixedSizeChunkingRequest,
    PageExclusion,
    StructuralChunkingRequest,
)
from dtos.responses import Chunk, DocType, ProcessResponse, StoredStrategy
from services.chunking import (
    Chunker,
    FixedSizeChunker,
    SemanticChunker,
    StructuralChunker,
)
from services.embedding import Embedder, OllamaEmbedder
from services.extraction import extractor_for
from services.storage import PostgresStorage

_PDF_MAGIC = b"%PDF-"
# A DOCX is a ZIP; the entry below is what distinguishes it from every other
# Office package (.xlsx, .pptx) that shares the container.
_ZIP_MAGIC = b"PK\x03\x04"
_DOCX_ENTRY = "word/document.xml"
# Markup that means "this is a document, not prose that mentions tags".
_HTML_MARKERS = (b"<!doctype html", b"<html", b"<head", b"<body")

# The %PDF- marker should sit at the very start, but some producers emit a few
# leading bytes; the spec tolerates it within the first chunk of the file. The
# HTML markers are looked for in the same window, for the same reason.
_MAGIC_SEARCH_WINDOW = 1024

# Declared content types that identify a format, checked only when the bytes are
# inconclusive. Matched as substrings, so charset parameters do not matter.
_CONTENT_TYPE_HINTS = (
    ("pdf", DocType.pdf),
    ("wordprocessingml", DocType.docx),
    ("msword", DocType.docx),
    ("html", DocType.html),
    ("text/", DocType.text),
)

# Filename extensions, the last resort. Markdown counts as text: the pipeline
# reads it as prose, and its markers are the ones the structural chunker looks for.
_EXTENSION_HINTS = (
    (".pdf", DocType.pdf),
    (".docx", DocType.docx),
    (".html", DocType.html),
    (".htm", DocType.html),
    (".xhtml", DocType.html),
    (".txt", DocType.text),
    (".text", DocType.text),
    (".md", DocType.text),
    (".markdown", DocType.text),
)

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

        Content sniffing takes precedence — the ``%PDF-`` marker, the
        ``word/document.xml`` entry inside a ZIP, or HTML's own tags. The
        declared ``content_type`` is consulted next and the ``filename``
        extension last, so a mislabelled file is still classified by its actual
        contents and only a format with no signature of its own (plain text)
        depends on what the caller claims.

        :attr:`DocType.unknown` is returned when nothing identifies the file,
        rather than defaulting to text: bytes that decode are not thereby prose,
        and ingesting a stray binary as a document would put its noise into the
        embeddings.
        """
        if _PDF_MAGIC in content[:_MAGIC_SEARCH_WINDOW]:
            return DocType.pdf
        if self._is_docx(content):
            return DocType.docx
        head = content[:_MAGIC_SEARCH_WINDOW].lower()
        if any(marker in head for marker in _HTML_MARKERS):
            return DocType.html
        if content_type:
            declared = content_type.lower()
            for hint, doc_type in _CONTENT_TYPE_HINTS:
                if hint in declared:
                    return doc_type
        if filename:
            name = filename.lower()
            for suffix, doc_type in _EXTENSION_HINTS:
                if name.endswith(suffix):
                    return doc_type
        return DocType.unknown

    @staticmethod
    def _is_docx(content: bytes) -> bool:
        """Is ``content`` an Office package holding a Word document?

        Guarded by the ZIP magic so the archive is only opened for bytes that
        could be one, and keyed on the Word body part so a ``.xlsx`` or ``.pptx``
        — same container, different contents — is not mistaken for a document.
        """
        if not content.startswith(_ZIP_MAGIC):
            return False
        try:
            with zipfile.ZipFile(BytesIO(content)) as package:
                return _DOCX_ENTRY in package.namelist()
        except zipfile.BadZipFile:
            return False

    @staticmethod
    def _extract_pages(content: bytes, doc_type: DocType) -> list[str]:
        """Extract ``content`` into per-page text, page 1 at index 0.

        Delegates to the extractor registered for ``doc_type`` (see
        :mod:`services.extraction`). Only ``pdf`` yields more than one page;
        the paginationless formats yield exactly one.

        Raises :class:`ValueError` if ``doc_type`` has no extractor, or if the
        bytes are not readable as that type.
        """
        extractor = extractor_for(doc_type)
        if extractor is None:
            raise ValueError(f"no extractor for document type '{doc_type.value}'")
        return extractor.extract(content)

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
        self,
        fixed_size: FixedSizeChunkingRequest,
        structural: StructuralChunkingRequest,
    ) -> dict[ChunkingStrategy, Chunker]:
        """The chunking strategies competing for this document."""
        return {
            ChunkingStrategy.fixed: FixedSizeChunker(fixed_size),
            ChunkingStrategy.semantic: SemanticChunker(self._get_embedder()),
            ChunkingStrategy.structural: StructuralChunker(structural),
        }

    def process(
        self,
        content: bytes,
        name: str,
        access_role: str,
        fixed_size: FixedSizeChunkingRequest | None = None,
        page_exclusion: PageExclusion | None = None,
        structural: StructuralChunkingRequest | None = None,
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

        Any type with an extractor is ingested — PDF, DOCX, HTML and plain text.
        A file whose type cannot be identified is reported as
        :attr:`DocType.unknown` and stored as nothing.

        ``fixed_size`` tunes the fixed-size candidate (defaulting to
        ``_DEFAULT_CHUNK_SIZE`` words) and ``structural`` the structural one (its
        heading patterns and size bounds); both fall back to their defaults.
        ``page_exclusion`` is strategy-agnostic and is applied before any chunking.
        The response reports which strategies were stored and their chunk counts.
        """
        doc_type = self._detect_doc_type(
            content, filename=filename, content_type=content_type
        )
        if extractor_for(doc_type) is None:
            return ProcessResponse(processed=len(content) > 0, doc_type=doc_type)

        pages = self._exclude_pages(
            self._extract_pages(content, doc_type), page_exclusion
        )
        fixed_size = fixed_size or FixedSizeChunkingRequest(
            chunk_size=_DEFAULT_CHUNK_SIZE
        )
        structural = structural or StructuralChunkingRequest()

        # Chunk, embed and persist one chunk at a time, for every strategy. Each
        # chunk is stored the moment it is created and embedded, so only a single
        # chunk (and its vector) is ever held in memory — rather than every
        # strategy's chunks accumulating for one batch insert. None is dropped
        # here; /evaluate scores the strategies and prunes the losers later.
        embedder = self._get_embedder()
        document_id: int | None = None
        strategies: list[StoredStrategy] = []
        for strategy, chunker in self._candidates(fixed_size, structural).items():
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
