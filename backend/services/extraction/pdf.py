"""PDF extraction (PyMuPDF).

The only format the pipeline ingests that carries real page boundaries, so it is
the only one whose per-page stats and page-scoped citations mean what they say.
Its fidelity is measured by ``evals/extraction_fidelity_eval.py``.
"""

import pymupdf


class PdfExtractor:
    """Extract a PDF's text, one entry per page."""

    def extract(self, content: bytes) -> list[str]:
        """Extract text from a PDF, one entry per page (page 1 at index 0).

        Raises :class:`ValueError` if ``content`` is not a readable PDF.
        """
        try:
            with pymupdf.open(stream=content, filetype="pdf") as document:
                return [page.get_text() for page in document]
        except Exception as exc:  # PyMuPDF surfaces several error types
            raise ValueError("content is not a readable PDF") from exc
