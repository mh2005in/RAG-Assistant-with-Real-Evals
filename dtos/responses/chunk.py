"""Response DTO for an embedded chunk.

A :class:`Chunk` is one retrievable unit: the page it came from, cheap
descriptive stats about that page's text, the text itself, and (once the
embedding stage has run) its vector. ``embedding`` is empty until an embedder
fills it, so a chunk can be built and inspected before it is embedded.
"""

from pydantic import BaseModel, Field

# Rough characters-per-token ratio for the ``page_token_count`` estimate. Real
# token counts are model/tokenizer specific and computed by the embedder at
# encode time; this keeps chunk-building cheap and dependency-free.
_CHARS_PER_TOKEN = 4

# Response-size caps. Full page text and 384-dim embeddings make a /process
# response enormous, so the response carries only a preview (see ``truncated``).
# The descriptive stats still describe the whole page and vector, so nothing is
# misrepresented — only the bulky payloads are clipped.
_TEXT_PREVIEW_CHARS = 200
_EMBEDDING_PREVIEW_DIMS = 8


class Chunk(BaseModel):
    """A page's text plus descriptive stats and, once embedded, its vector."""

    page_number: int = Field(..., ge=1, description="1-based source page number.")
    page_char_count: int = Field(..., ge=0, description="Characters in the text.")
    page_word_count: int = Field(..., ge=0, description="Whitespace-split words.")
    page_sentence_count_raw: int = Field(
        ...,
        ge=0,
        description="Naive sentence count (non-empty pieces split on '. ').",
    )
    page_token_count: float = Field(
        ...,
        ge=0,
        description="Estimated token count (~chars / 4), not an exact tokenization.",
    )
    text: str = Field(..., description="The chunk's text.")
    embedding: list[float] = Field(
        default_factory=list,
        description="Embedding vector; empty until the embedding stage fills it.",
    )

    @classmethod
    def from_page(cls, page_number: int, text: str) -> "Chunk":
        """Build a chunk for one page, computing its descriptive stats.

        The embedding is left empty; run the text through an embedder to fill it.
        """
        sentences = [piece for piece in text.split(". ") if piece.strip()]
        return cls(
            page_number=page_number,
            page_char_count=len(text),
            page_word_count=len(text.split()),
            page_sentence_count_raw=len(sentences),
            page_token_count=len(text) / _CHARS_PER_TOKEN,
            text=text,
        )

    def truncated(
        self,
        *,
        text_chars: int = _TEXT_PREVIEW_CHARS,
        embedding_dims: int = _EMBEDDING_PREVIEW_DIMS,
    ) -> "Chunk":
        """Return a copy with ``text`` and ``embedding`` clipped for the response.

        Only the bulky payloads are shortened — to ``text_chars`` characters and
        ``embedding_dims`` dimensions. ``page_number`` and every ``page_*`` stat
        are left untouched, so they still describe the full page and vector.
        """
        return self.model_copy(
            update={
                "text": self.text[:text_chars],
                "embedding": self.embedding[:embedding_dims],
            }
        )
