"""Sentence splitting shared by the chunking stage.

Both the semantic strategy (which needs sentence boundaries to find topic shifts)
and the coherence metric (which scores sentences within a chunk) split text the
same way, so they agree on what a sentence is.
"""

import re

# Split on sentence-ending punctuation followed by whitespace. Deliberately
# dependency-free; good enough for prose, and callers only need reasonable
# sentence boundaries, not perfect ones.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split ``text`` into non-empty, stripped sentences."""
    return [piece.strip() for piece in _SENTENCE_BOUNDARY.split(text) if piece.strip()]
