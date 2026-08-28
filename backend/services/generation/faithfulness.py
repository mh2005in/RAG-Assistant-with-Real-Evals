"""Answer faithfulness: is a generated answer grounded in its context?

The generation stage's quality metric, and the counterpart to
:mod:`services.chunking.coherence` — that one scores how a document was cut up,
this one scores what the model did with what it retrieved.

``/answer`` builds a numbered, cited context and asks the model to use only that
(see :meth:`services.answering.Answering.build_prompt`). Whether it obeyed is a
*quality* claim, so per CLAUDE.md it needs measuring rather than asserting. This
module measures it **without an LLM judge**: the answer is split into
sentence-level claims, each claim is embedded, and a claim counts as grounded when
it is close enough to something in the context. That keeps the metric
deterministic, free, and runnable offline against the same local embedding model
the rest of the pipeline uses — the same reasoning that keeps ``/evaluate``
LLM-free. An LLM judge would read entailment rather than similarity and is scoped
separately (``REQ-EVL-05``).

**Claims are matched against context *sentences*, not whole chunks**, and that
choice is load-bearing. A chunk's embedding is dominated by its overall topic, so
matching against it scores any on-topic sentence highly and an invented claim
about the right subject passes just as easily as a quoted one — the first cut of
this metric could not separate a grounded answer from an ungrounded one for
exactly that reason. A sentence is specific enough that a claim has to resemble
something the document actually says. Each sentence remembers which chunk it came
from, so citations are still scored per chunk.

Two families of number come out of it:

* **support** — does *anything* in the retrieved context back this claim? ``faithfulness`` is the
  fraction of claims that clear the threshold; ``mean_support`` is the same signal
  without one, so a ranking never hinges on where the line was drawn.
* **citation** — the answer is asked to cite like ``[1]``, so the markers are
  checked too: ``citation_validity`` catches a citation pointing at a chunk that
  was never in the context, and ``cited_support`` asks whether the chunk a claim
  actually *cites* is the one that backs it. A fluent answer citing the wrong
  source is exactly the failure a support-only metric misses.

**Known property:** an honest abstention ("I don't know") is a claim no chunk
supports, so it scores as unfaithful. The metric reads similarity, not intent.
That is why ``claims`` is reported next to the scores, and why the numbers are
meant to be compared between conditions rather than read as absolutes.
"""

import re

import numpy as np
from pydantic import BaseModel, Field

from services.chunking import split_sentences
from services.embedding import Embedder

# A claim is "supported" when its best cosine similarity to a context sentence is
# at least this high. Public because the eval records the threshold its numbers
# were produced under, and sweeps it to show the choice still holds.
#
# Calibrated from the eval, not guessed: over its three conditions the grounded
# claims' *lowest* support was 0.765 and the distractor claims' 75th percentile
# was 0.720, so the cut sits in the gap between them. The eval sweeps it on every
# run (``threshold_sweep`` in the artifact).
#
# The rule is "the highest cut that still accepts essentially every grounded
# claim", not "the cut with the biggest grounded-minus-distractor gap" — the gap
# alone is a trap. On one run 0.85 showed the widest gap, but only by rejecting a
# third of genuinely grounded claims, which is a worse place to operate than 0.75
# whatever the gap says. At 0.75 the grounded rate has held at 0.91-1.00 across
# runs while the distractor rate sits at 0.20-0.30.
#
# It is deliberately *higher* than the 0.6 ``services.evaluation`` uses for
# hit_rate. That one compares an expected answer against a whole retrieved chunk;
# this compares one sentence against one sentence, which starts from a higher
# baseline similarity, so the same number would not mean the same thing.
#
# Two caveats worth keeping in mind: the number is specific to nomic-embed-text,
# and it was fitted on 8 questions over 2 documents whose generated answers vary
# between runs. Nothing ranks on it —
# ``mean_support`` is the continuous companion, and it is the more trustworthy of
# the two; the threshold only turns the signal into a rate.
SUPPORT_THRESHOLD = 0.75

# Citation markers the prompt asks for: ``[1]``, and ``[1, 2]`` for a claim drawn
# from more than one chunk. The leading whitespace is part of the match so that
# removing a marker closes the gap it leaves -- "finds [1]." must strip to
# "finds.", not to "finds .", which would be a different string to embed.
_CITATION = re.compile(r"\s*\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")


class ClaimSupport(BaseModel):
    """One sentence of the answer, and what in the context backs it."""

    claim: str = Field(..., description="The answer sentence, citations stripped.")
    support: float = Field(
        ..., description="Best cosine similarity to any context sentence."
    )
    supported: bool = Field(
        ..., description="Whether ``support`` cleared the support threshold."
    )
    best_chunk: int | None = Field(
        default=None, description="1-based context chunk that best backs the claim."
    )
    citations: list[int] = Field(
        default_factory=list, description="Citation markers found in the claim."
    )
    invalid_citations: list[int] = Field(
        default_factory=list, description="Markers naming a chunk not in the context."
    )
    cited_support: float | None = Field(
        default=None,
        description="Best similarity among the sentences of the claim's cited "
        "chunks; None when it cited nothing valid.",
    )


class FaithfulnessScore(BaseModel):
    """How well one generated answer is grounded in the context it was given."""

    claims: int = Field(..., ge=0, description="Sentence-level claims scored.")
    faithfulness: float = Field(
        ..., description="Fraction of claims supported by a context sentence."
    )
    mean_support: float = Field(
        ..., description="Mean best similarity per claim; threshold-free."
    )
    citation_coverage: float | None = Field(
        default=None,
        description="Fraction of claims carrying a citation; None if no claims.",
    )
    citation_validity: float | None = Field(
        default=None,
        description="Fraction of citation markers naming a real chunk; None when the "
        "answer cited nothing.",
    )
    cited_support: float | None = Field(
        default=None,
        description="Mean similarity between a claim and the chunks it cites; None "
        "when nothing was validly cited.",
    )
    supports: list[ClaimSupport] = Field(
        default_factory=list, description="Per-claim detail, in answer order."
    )


def _similarities(vector: list[float], matrix: list[list[float]]) -> np.ndarray:
    """Cosine similarity of ``vector`` against every row of ``matrix``.

    A zero-norm vector contributes 0.0 rather than a division-by-zero, matching
    how ``services.evaluation`` scores against an empty retrieval.
    """
    left = np.asarray(vector, dtype=float)
    rows = np.asarray(matrix, dtype=float)
    denom = np.linalg.norm(rows, axis=1) * float(np.linalg.norm(left))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denom > 0, (rows @ left) / denom, 0.0)


def _parse_citations(claim: str) -> tuple[str, list[int]]:
    """Strip citation markers from ``claim`` and return them as 1-based indices.

    The markers are removed before embedding so a claim is scored on what it says,
    not on how many brackets it carries. Duplicates collapse, order is kept.
    """
    cited: list[int] = []
    for group in _CITATION.findall(claim):
        for number in group.split(","):
            index = int(number.strip())
            if index not in cited:
                cited.append(index)
    return " ".join(_CITATION.sub("", claim).split()), cited


def _mean(values: list[float]) -> float:
    """Arithmetic mean of a non-empty list."""
    return sum(values) / len(values)


def _context_sentences(context: list[str]) -> tuple[list[str], list[int]]:
    """Flatten ``context`` to sentences, and say which chunk each one came from.

    A chunk with no sentence-ending punctuation still counts as one sentence,
    otherwise it would silently drop out of the comparison.
    """
    sentences: list[str] = []
    owners: list[int] = []
    for index, chunk in enumerate(context):
        for sentence in split_sentences(chunk) or ([chunk] if chunk.strip() else []):
            sentences.append(sentence)
            owners.append(index)
    return sentences, owners


def score_answer(
    answer: str, context: list[str], embedder: Embedder
) -> FaithfulnessScore:
    """Score how far ``answer`` is grounded in ``context``.

    ``context`` is the chunk text in the order the prompt numbered it, so a
    citation ``[1]`` refers to ``context[0]``. Every claim and every context
    sentence is embedded in one batch, so the comparison is on identical footing.

    An empty answer, or an answer scored against no context, has nothing to ground
    and returns zeros.
    """
    parsed = [_parse_citations(sentence) for sentence in split_sentences(answer)]
    claims = [(text, cited) for text, cited in parsed if text]
    sentences, owners = _context_sentences(context)
    if not claims or not sentences:
        return FaithfulnessScore(claims=len(claims), faithfulness=0.0, mean_support=0.0)

    vectors = embedder.embed([text for text, _ in claims] + sentences)
    sentence_vectors = vectors[len(claims) :]

    supports: list[ClaimSupport] = []
    for (text, cited), vector in zip(claims, vectors[: len(claims)]):
        sims = _similarities(vector, sentence_vectors)
        valid = [index for index in cited if 1 <= index <= len(context)]
        cited_sims = [
            sims[position]
            for position, owner in enumerate(owners)
            if owner + 1 in valid
        ]
        supports.append(
            ClaimSupport(
                claim=text,
                support=round(float(sims.max()), 4),
                supported=bool(sims.max() >= SUPPORT_THRESHOLD),
                best_chunk=owners[int(sims.argmax())] + 1,
                citations=cited,
                invalid_citations=[index for index in cited if index not in valid],
                cited_support=(
                    round(float(max(cited_sims)), 4) if cited_sims else None
                ),
            )
        )

    markers = [index for support in supports for index in support.citations]
    valid_markers = [
        index
        for support in supports
        for index in support.citations
        if index not in support.invalid_citations
    ]
    cited_supports = [s.cited_support for s in supports if s.cited_support is not None]
    return FaithfulnessScore(
        claims=len(supports),
        faithfulness=round(_mean([float(s.supported) for s in supports]), 4),
        mean_support=round(_mean([s.support for s in supports]), 4),
        citation_coverage=round(_mean([float(bool(s.citations)) for s in supports]), 4),
        citation_validity=(
            round(len(valid_markers) / len(markers), 4) if markers else None
        ),
        cited_support=round(_mean(cited_supports), 4) if cited_supports else None,
        supports=supports,
    )
