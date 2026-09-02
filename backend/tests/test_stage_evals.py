"""Tests for the metric helpers the stage-coverage evals compute themselves.

The chunking, retrieval and faithfulness evals score with shipped modules
(``coherence``, ``rank_metrics``, ``faithfulness``) that are tested next to the
services they belong to. The extraction, embedding and storage evals compute
metrics no service needs, so those live in the eval modules — and are tested here
rather than left to be checked by reading them.

Everything here is offline: no Ollama, no database. The PDFs are built in memory
by the extraction eval's own generator, which is the point — a metric that reads
a real PDF round trip is worth proving against one.
"""

import numpy as np
import pytest

from evals.embedding_quality_eval import (
    _DOCUMENT,
    _QUERY,
    _accuracy_and_margin,
    _LexicalArm,
    _PrefixedArm,
    _RandomArm,
    _score_triplets,
)
from evals.extraction_fidelity_eval import (
    _build_pdf,
    _exclusion_round_trip,
    _fidelity,
    _paginate,
    _score_arm,
)
from evals.storage_index_eval import _grow_corpus, _score


class _StubEmbedder:
    """Records the texts it was asked to embed and returns a canned vector."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.seen.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    def embed_chunks(self, chunks: list) -> list:  # pragma: no cover - unused here
        raise NotImplementedError


# --- extraction: pagination ------------------------------------------------


def test_paginate_keeps_every_word_and_fills_every_page() -> None:
    source = ["\n\n".join(f"paragraph {index} has five words" for index in range(9))]

    pages = _paginate(source, 3)

    assert len(pages) == 3
    assert all(page.split() for page in pages)
    assert " ".join(pages).split() == source[0].split()


def test_paginate_never_overflows_the_last_page() -> None:
    # More pages than paragraphs: the tail pages have nothing to take.
    pages = _paginate(["only one paragraph here"], 3)

    assert len(pages) == 3
    assert " ".join(pages).split() == ["only", "one", "paragraph", "here"]


# --- extraction: fidelity metrics ------------------------------------------


def test_fidelity_is_perfect_on_an_identical_sequence() -> None:
    words = ["alpha", "beta", "gamma"]

    assert _fidelity(words, list(words)) == {
        "recall": 1.0,
        "precision": 1.0,
        "order_fidelity": 1.0,
    }


def test_reordering_costs_order_fidelity_but_not_recall() -> None:
    words = ["alpha", "beta", "gamma", "delta"]

    scored = _fidelity(words, list(reversed(words)))

    assert scored["recall"] == 1.0
    assert scored["precision"] == 1.0
    assert scored["order_fidelity"] < 1.0


def test_dropped_words_cost_recall_and_spurious_words_cost_precision() -> None:
    truth = ["alpha", "beta", "gamma", "delta"]

    assert _fidelity(truth, ["alpha", "beta"])["recall"] == 0.5
    assert _fidelity(truth, [*truth, "epsilon", "zeta"])["precision"] < 1.0


def test_words_on_the_wrong_page_cost_page_recall_but_not_document_recall() -> None:
    truth = ["alpha beta", "gamma delta"]
    # Every word survives, but page 2's words were extracted onto page 1.
    merged = ["alpha beta gamma delta", ""]

    scored = _score_arm(truth, merged)

    assert scored["document_recall"] == 1.0
    assert scored["page_recall"] < 1.0


def test_a_missing_page_is_scored_rather_than_ignored() -> None:
    scored = _score_arm(["alpha beta", "gamma delta"], ["alpha beta"])

    assert scored["page_recall"] == 0.5
    assert scored["document_recall"] == 0.5


# --- extraction: page exclusion through a real PDF -------------------------


def test_exclusion_blanks_the_page_without_renumbering_the_rest() -> None:
    truth = _paginate(
        ["\n\n".join(f"page {index} carries word{index}" for index in range(6))], 3
    )
    content, _ = _build_pdf(truth, "single_column")

    result = _exclusion_round_trip(truth, content)

    # The regression this guards: passing the wrong field name to PageExclusion
    # silently excludes nothing, and only leaked_words notices.
    assert result["leaked_words"] == 0
    assert result["kept_recall"] == 1.0
    assert result["page_numbering_preserved"] is True
    assert result["pages_after_exclusion"] == 3


# --- embedding: arms -------------------------------------------------------


def test_lexical_arm_scores_shared_vocabulary_and_ignores_disjoint_text() -> None:
    arm = _LexicalArm(["alpha beta", "gamma delta"])

    same, other = arm.vectors(["alpha beta", "gamma delta"], _DOCUMENT)

    assert np.dot(same, same) > 0.0
    assert np.dot(same, other) == pytest.approx(0.0)


def test_random_arm_is_a_function_of_its_input() -> None:
    arm = _RandomArm(seed=1, dims=8)

    first, second = arm.vectors(["alpha", "alpha"], _DOCUMENT)
    (other,) = arm.vectors(["beta"], _DOCUMENT)

    assert first == second
    assert first != other


def test_prefixed_arm_sends_a_different_prefix_per_role() -> None:
    embedder = _StubEmbedder()
    arm = _PrefixedArm(embedder)

    arm.vectors(["a question"], _QUERY)
    arm.vectors(["a chunk"], _DOCUMENT)

    assert embedder.seen == ["search_query: a question", "search_document: a chunk"]


# --- embedding: triplet scoring --------------------------------------------


def _vectors(mapping: dict[tuple[str, str], list[float]]) -> dict:
    return {key: np.asarray(value, dtype=float) for key, value in mapping.items()}


def test_triplet_is_correct_when_the_positive_is_closest() -> None:
    triplets = [
        {
            "anchor": "a",
            "positive": "p",
            "hard_negative": "h",
            "easy_negative": "e",
            "hard_negative_kind": "inversion",
        }
    ]
    vectors = _vectors(
        {
            (_QUERY, "a"): [1.0, 0.0],
            (_DOCUMENT, "p"): [1.0, 0.0],
            (_DOCUMENT, "h"): [0.0, 1.0],
            (_DOCUMENT, "e"): [0.0, 1.0],
        }
    )

    scored = _score_triplets(triplets, vectors)

    assert scored["hard_accuracy"] == 1.0
    assert scored["hard_margin"] == pytest.approx(1.0)
    assert scored["positive_cosine"] == pytest.approx(1.0)


def test_triplet_is_wrong_when_the_negative_is_closest() -> None:
    triplets = [
        {
            "anchor": "a",
            "positive": "p",
            "hard_negative": "h",
            "easy_negative": "e",
            "hard_negative_kind": "inversion",
        }
    ]
    vectors = _vectors(
        {
            (_QUERY, "a"): [1.0, 0.0],
            (_DOCUMENT, "p"): [0.0, 1.0],
            (_DOCUMENT, "h"): [1.0, 0.0],
            (_DOCUMENT, "e"): [0.0, 1.0],
        }
    )

    scored = _score_triplets(triplets, vectors)

    assert scored["hard_accuracy"] == 0.0
    assert scored["hard_margin"] == pytest.approx(-1.0)


def test_accuracy_counts_only_strictly_positive_margins() -> None:
    # A tie is not a win: the negative is as close as the paraphrase.
    assert _accuracy_and_margin([0.5, 0.0, -0.5]) == (round(1 / 3, 4), 0.0)


# --- storage: corpus and recall --------------------------------------------


def test_grown_corpus_keeps_rows_near_the_base_they_came_from() -> None:
    base = np.eye(4, dtype=float)

    corpus, sources, mean_cosine = _grow_corpus(
        base, rows=12, rng=np.random.default_rng(0)
    )

    assert corpus.shape == (12, 4)
    # Round-robin over the base vectors, so every base is represented.
    assert sources == [index % 4 for index in range(12)]
    assert np.allclose(np.linalg.norm(corpus, axis=1), 1.0)
    assert mean_cosine > 0.9


def test_recall_against_exact_search_reads_set_overlap() -> None:
    exact = [[1, 2, 3], [4, 5, 6]]

    perfect = _score(exact, exact, [1.0, 1.0])
    partial = _score([[1, 2, 9], [4, 9, 9]], exact, [1.0, 1.0])
    missed = _score([[7, 8, 9], [7, 8, 9]], exact, [1.0, 1.0])

    assert perfect["recall_vs_exact"] == 1.0
    assert perfect["top1_agreement"] == 1.0
    assert partial["recall_vs_exact"] == pytest.approx(0.5)
    assert missed["recall_vs_exact"] == 0.0
    assert missed["top1_agreement"] == 0.0
