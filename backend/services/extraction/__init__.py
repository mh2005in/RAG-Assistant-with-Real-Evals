"""Extraction stage: document bytes in, per-page text out.

One extractor per ingestible :class:`~dtos.responses.DocType`, each behind the
:class:`~services.extraction.base.Extractor` interface, so the stage can gain a
format without the chunking, embedding or storage stages knowing. Detecting
*which* type a file is belongs to ``/process``
(:class:`~services.file_processing.FileProcessing`); choosing the extractor for a
known type belongs here.
"""

from dtos.responses import DocType
from services.extraction.base import Extractor, single_page
from services.extraction.docx import DocxExtractor
from services.extraction.html import HtmlExtractor
from services.extraction.pdf import PdfExtractor
from services.extraction.text import TextExtractor

# Stateless, so one instance each is shared by every request.
_EXTRACTORS: dict[DocType, Extractor] = {
    DocType.pdf: PdfExtractor(),
    DocType.docx: DocxExtractor(),
    DocType.html: HtmlExtractor(),
    DocType.text: TextExtractor(),
}


def extractor_for(doc_type: DocType) -> Extractor | None:
    """The extractor for ``doc_type``, or ``None`` if nothing can read it.

    ``None`` is the answer for :attr:`DocType.unknown` alone — a file whose type
    could not be identified is not ingested, rather than guessed at.
    """
    return _EXTRACTORS.get(doc_type)


__all__ = [
    "DocxExtractor",
    "Extractor",
    "HtmlExtractor",
    "PdfExtractor",
    "TextExtractor",
    "extractor_for",
    "single_page",
]
