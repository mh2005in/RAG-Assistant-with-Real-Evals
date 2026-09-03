"""Plain-text extraction.

The degenerate case: the bytes already are the text. It still goes through the
:class:`~services.extraction.base.Extractor` seam rather than being special-cased
in the caller, so every format is read the same way and the eval can score them
side by side.
"""

from services.extraction.base import single_page

# utf-8-sig strips a leading byte-order mark if there is one and behaves exactly
# like utf-8 when there is not. Undecodable bytes become U+FFFD rather than
# failing the upload: a file that is mostly text should still be ingestible.
_ENCODING = "utf-8-sig"


class TextExtractor:
    """Decode a plain-text document to the one page it has."""

    def extract(self, content: bytes) -> list[str]:
        """Decode ``content`` as UTF-8 text on a single page."""
        return single_page(content.decode(_ENCODING, errors="replace").split("\n\n"))
