"""DOCX extraction (python-docx).

Paginationless: a ``.docx`` stores a flow of blocks and leaves page breaks to
whatever renders it, so the whole document extracts to a single page (see
:mod:`services.extraction.base`).

The body is walked in document order rather than through ``document.paragraphs``,
which reports body paragraphs only and would silently drop every table — and
appending the tables afterwards would put their text in the wrong place. A table
is flattened one row per block, its cells joined into a single line, so a row's
cells stay together for the chunking stage instead of each becoming its own
paragraph.
"""

from io import BytesIO

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from services.extraction.base import single_page

_PARAGRAPH_TAG = qn("w:p")
_TABLE_TAG = qn("w:tbl")


class DocxExtractor:
    """Extract a Word document's text as one page, in document order."""

    def extract(self, content: bytes) -> list[str]:
        """Extract ``content`` as a single page of text.

        Raises :class:`ValueError` if ``content`` is not a readable DOCX.
        """
        try:
            document = Document(BytesIO(content))
        except Exception as exc:  # python-docx raises several package errors
            raise ValueError("content is not a readable DOCX") from exc
        return single_page(self._blocks(document))

    @staticmethod
    def _blocks(document: DocxDocument) -> list[str]:
        """The body's paragraphs and table rows, in the order they appear."""
        blocks: list[str] = []
        for element in document.element.body.iterchildren():
            if element.tag == _PARAGRAPH_TAG:
                blocks.append(Paragraph(element, document).text)
            elif element.tag == _TABLE_TAG:
                blocks.extend(
                    " ".join(cell.text for cell in row.cells)
                    for row in Table(element, document).rows
                )
        return blocks
