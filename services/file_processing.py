"""File-processing service.

Orchestrates the ingestion pipeline for an uploaded file: detect the document
type, extract text, and chunk it with the requested strategy. Route handlers
stay thin and delegate here (see CLAUDE.md).
"""

from dtos.requests import ChunkingStrategy, FixedSizeChunkingRequest
from dtos.responses import DocType, ProcessResponse
from services.chunking import FixedSizeChunker
from services.doc_type import detect_doc_type
from services.pdf_extraction import extract_pdf_pages


def process_file(
    content: bytes,
    strategy: ChunkingStrategy,
    fixed_size: FixedSizeChunkingRequest | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> ProcessResponse:
    """Detect the document type and, for PDFs, chunk it.

    ``fixed_size`` carries the fixed-size chunking parameters and is required
    when ``strategy`` is :attr:`ChunkingStrategy.fixed`.

    Currently only PDFs chunked with the fixed-size strategy produce chunks;
    other document types and strategies are detected/accepted but return no
    chunks yet (they are wired in as the pipeline matures).
    """
    if strategy is ChunkingStrategy.fixed and fixed_size is None:
        raise ValueError("fixed_size parameters are required for the 'fixed' strategy")

    doc_type = detect_doc_type(content, filename=filename, content_type=content_type)

    if doc_type is DocType.pdf and strategy is ChunkingStrategy.fixed:
        assert fixed_size is not None  # guaranteed by the guard above
        pages = extract_pdf_pages(content)
        chunks = FixedSizeChunker(fixed_size).chunk(pages)
        return ProcessResponse(
            processed=True,
            doc_type=doc_type,
            chunk_count=len(chunks),
            chunks=chunks,
        )

    return ProcessResponse(processed=len(content) > 0, doc_type=doc_type)
