"""HTML extraction (BeautifulSoup).

Paginationless, like DOCX: an HTML document is a flow that a browser paginates at
render time, so it extracts to a single page (see :mod:`services.extraction.base`).

Two things separate this from decoding the bytes. **Non-content is removed** —
scripts, styles and the head carry text that no reader ever sees, and leaving it
in would put minified JavaScript into the chunks and the embeddings.
**Block-level tags become blank lines** — HTML marks its structure with tags, not
with whitespace, so ``<p>one</p><p>two</p>`` has no separator at all until one is
inserted; without this every heading and paragraph in a document would run
together into a single block. Inline tags are deliberately left alone, so
``<b>bold</b>face`` stays one word.

The same parse is what a scraped page (``REQ-EXT-05``) will be read with, which is
why the markup handling lives here rather than in a scraping-specific path.
"""

from bs4 import BeautifulSoup

from services.extraction.base import single_page

# Text inside these is never shown to a reader.
_NON_CONTENT_TAGS = ["script", "style", "noscript", "template", "head"]

# Tags that start a new block of prose. A blank line is inserted around each so
# the chunking stage sees the paragraph breaks the markup implies.
_BLOCK_TAGS = [
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "dd",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
]

# html.parser is the standard library's; it keeps the runtime free of a C parser
# and is lenient enough for the malformed markup real pages ship.
_PARSER = "html.parser"
_BLOCK_BREAK = "\n\n"


class HtmlExtractor:
    """Extract an HTML document's readable text as one page."""

    def extract(self, content: bytes) -> list[str]:
        """Extract the readable text of ``content`` as a single page."""
        soup = BeautifulSoup(content, _PARSER)
        for tag in soup.find_all(_NON_CONTENT_TAGS):
            tag.decompose()
        for tag in soup.find_all(_BLOCK_TAGS):
            tag.insert_before(_BLOCK_BREAK)
            tag.insert_after(_BLOCK_BREAK)
        # Empty separator: the block breaks above already carry the structure,
        # and a separator here would split inline runs mid-word.
        return single_page(soup.get_text("").split(_BLOCK_BREAK))
