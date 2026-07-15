"""Document-type detection (extraction stage).

Identifies the type of an uploaded file so downstream stages can pick the right
extractor. Detection is content-based (magic bytes) first; the filename
extension and declared content type are consulted only as fallbacks.
"""

from dtos.responses import DocType

_PDF_MAGIC = b"%PDF-"
# The %PDF- marker should appear at the very start, but some producers emit a
# few leading bytes; the spec tolerates it within the first chunk of the file.
_MAGIC_SEARCH_WINDOW = 1024


def detect_doc_type(
    content: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> DocType:
    """Identify the document type of ``content``.

    Content sniffing (the leading ``%PDF-`` marker) takes precedence. The
    ``filename`` extension and declared ``content_type`` are used only when the
    bytes are inconclusive, so a mislabelled file is still classified by its
    actual contents.
    """
    if _PDF_MAGIC in content[:_MAGIC_SEARCH_WINDOW]:
        return DocType.pdf
    if content_type and "pdf" in content_type.lower():
        return DocType.pdf
    if filename and filename.lower().endswith(".pdf"):
        return DocType.pdf
    return DocType.unknown
