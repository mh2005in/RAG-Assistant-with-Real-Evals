"""Embedding-quality eval for the embedding stage (``REQ-EVL-02``).

The chunking, retrieval and faithfulness evals all *use* the embedder — to find
topic shifts, to rank chunks, to score claims — but none of them measures it. Its
output is the coordinate system every one of those numbers is computed in, so when
it is wrong they are all quietly wrong together.

The embedding stage makes one quality claim: text that means the same thing lands
close together, and text that does not lands apart. That is measured directly,
with triplets. Each triplet is an anchor, one paraphrase of it, and two things it
should sit further from:

====================  ==========================================================
member                how it is written
====================  ==========================================================
``positive``          the anchor's meaning in deliberately different words, so
                      word overlap cannot carry it
``hard_negative``     the anchor's *vocabulary*, not its meaning — either an
                      ``inversion`` (the claim reversed in near-identical
                      wording) or an ``adjacent_fact`` (a different, neighbouring
                      fact from the same document)
``easy_negative``     a sentence from elsewhere in the corpus, on another subject
====================  ==========================================================

A model scores a triplet correctly when the positive is closer to the anchor than
the negative is. The two negatives are reported separately because they ask
different questions: the easy negative asks whether the model knows what the text
is *about*, the hard negative whether it knows what the text *says*. Anything that
beats the easy negatives and not the hard ones is a topic detector being used as a
meaning detector.

**Four arms, so the numbers mean something.**

=========================  =======================================  =============
arm                        what it is                               expectation
=========================  =======================================  =============
``ollama``                 the shipped :class:`OllamaEmbedder`,     the number
                           called exactly as the pipeline calls     that describes
                           it — no task prefix                      the system
``ollama+task-prefix``     the same model and server, with the      unknown; the
                           model's documented ``search_query:`` /   point of the
                           ``search_document:`` prefixes            arm
``lexical-tfidf``          bag-of-words TF-IDF cosine, fitted on    a real floor
                           this eval's own texts — no model, no
                           server, no network
``random``                 a fixed random unit vector per text      control, ~0.5
=========================  =======================================  =============

``lexical-tfidf`` is the baseline the stage has to earn its keep against: it is
free and instant, so a learned embedder that only matches it is buying nothing.
``random`` is a control, not a candidate — it must land at chance, and if it does
not, the metric is reading something other than similarity. ``ollama+task-prefix``
is there because the shipped code sends bare text to a model whose authors
document a prefix for each role, and "does that matter here" should be a number
rather than an opinion. It changes nothing in the pipeline; it only says whether
there is anything to change.

Roles are assigned the way the system uses them: an anchor is a ``query`` (it
stands in for a user's question) and everything else is a ``document`` (it stands
in for a stored chunk). Only the prefixed arm reads the role; the others ignore
it, which is exactly the difference being measured.

**The similarity floor.** Two thresholds are hard-coded in this system —
``ANSWER_MATCH_THRESHOLD`` (0.6) decides which chunks count as relevant for
``/evaluate``'s hit rate and rank metrics, and ``SUPPORT_THRESHOLD`` (0.75)
decides which claims count as grounded. Both are absolute cosine cut-offs, so both
mean only what this corpus's *arbitrary* pairs already score. The eval therefore
also reports the cosine distribution over every pair of corpus sentences and the
share each threshold would admit: a threshold that most of the corpus already
clears is not separating anything.

The triplet set is small — 16 hand-written triplets over the two sample documents
— so read the accuracies as direction, not as a benchmark result. Everything but
the Ollama calls is deterministic, and the random arm is seeded per text.

Run it with:
    OLLAMA_BASE_URL=http://localhost:11434 uv run python -m evals.embedding_quality_eval

It needs a running Ollama for the two model arms, and no database. Results are
written to ``evals/results/embedding_quality.json`` and are a regenerable
artifact, not a one-off screenshot.
"""

import json
import math
import random
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from evals.fixed_size_chunking_eval import _load_pages
from services.chunking.sentences import split_sentences
from services.embedding import Embedder, OllamaEmbedder
from services.evaluation import ANSWER_MATCH_THRESHOLD
from services.generation import SUPPORT_THRESHOLD

_DATA_DIR = Path(__file__).parent / "data"
_TRIPLETS_PATH = _DATA_DIR / "embedding_triplets.json"
_RESULTS_PATH = Path(__file__).parent / "results" / "embedding_quality.json"

# Flat prose first, then a document that marks up its own structure -- the same
# two fixtures the other evals use, so every eval talks about one corpus.
_DATASETS = ["sample.txt", "structured_sample.txt"]

_NEGATIVES = ["hard_negative", "easy_negative"]

# What a text stands in for. An anchor plays the part of a user's question; every
# other text plays the part of a stored chunk.
_QUERY = "query"
_DOCUMENT = "document"

# Dimension of the random control's vectors; matches the shipped model, so the
# control is a stand-in for it rather than a differently-shaped thing.
_RANDOM_DIMS = 768
_SEED = 20260902

_TOKEN = re.compile(r"[a-z0-9]+")


class _Arm(Protocol):
    """One way of turning text into vectors, told what part the text plays."""

    def vectors(self, texts: list[str], role: str) -> list[list[float]]: ...


class _PlainArm:
    """The shipped embedder, called exactly as the pipeline calls it.

    The role is accepted and ignored: ``OllamaEmbedder.embed`` takes bare text
    and that is the whole point of this arm — it is what the system does today.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def vectors(self, texts: list[str], role: str) -> list[list[float]]:
        return self._embedder.embed(texts)


class _PrefixedArm:
    """The same model and server, called the way the model documents.

    ``nomic-embed-text`` is trained with a task prefix on every input, and asks
    for a different one depending on whether the text is being searched *for* or
    searched *over*. Nothing else changes — same server, same model, same
    dimensions — so any difference is the prefix.
    """

    _PREFIXES = {_QUERY: "search_query: ", _DOCUMENT: "search_document: "}

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def vectors(self, texts: list[str], role: str) -> list[list[float]]:
        prefix = self._PREFIXES[role]
        return self._embedder.embed([prefix + text for text in texts])


class _LexicalArm:
    """TF-IDF bag of words — the baseline a learned embedder has to beat.

    Fitted on the eval's own texts, which is the friendliest possible setting for
    it: the idf weights are computed over exactly the sentences it will be scored
    on, so no word it meets is out of vocabulary. Anything it still gets wrong is
    a limit of matching words, not of the sample. The role is ignored — a bag of
    words has no notion of one.
    """

    def __init__(self, corpus: list[str]) -> None:
        documents = [self._tokens(text) for text in corpus]
        self._vocabulary = {
            term: index
            for index, term in enumerate(
                sorted({term for document in documents for term in document})
            )
        }
        total = len(documents)
        frequencies = Counter(term for document in documents for term in set(document))
        # Smoothed idf: +1 top and bottom so an unseen term cannot divide by zero,
        # and +1 outside so a term in every document still carries some weight.
        self._idf = {
            term: math.log((1 + total) / (1 + frequencies[term])) + 1.0
            for term in self._vocabulary
        }

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return _TOKEN.findall(text.lower())

    def vectors(self, texts: list[str], role: str) -> list[list[float]]:
        rows = []
        for text in texts:
            tokens = self._tokens(text)
            vector = [0.0] * len(self._vocabulary)
            for term, count in Counter(tokens).items():
                index = self._vocabulary.get(term)
                if index is not None:
                    vector[index] = (count / len(tokens)) * self._idf[term]
            rows.append(vector)
        return rows


class _RandomArm:
    """A fixed random vector per text — the control arm.

    Seeded from the text itself, so it is a *function* of its input (the same
    sentence always gets the same vector) while carrying none of its meaning.
    Everything it scores is chance, which is the point: it says what these metrics
    read when there is no signal at all.
    """

    def __init__(self, seed: int, dims: int) -> None:
        self._seed = seed
        self._dims = dims

    def vectors(self, texts: list[str], role: str) -> list[list[float]]:
        rows = []
        for text in texts:
            generator = random.Random(f"{self._seed}:{text}")
            rows.append([generator.gauss(0.0, 1.0) for _ in range(self._dims)])
        return rows


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    """Cosine similarity, with a zero-norm vector scoring 0.0 rather than NaN."""
    denominator = float(np.linalg.norm(left)) * float(np.linalg.norm(right))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(left, right) / denominator)


# A vector lookup is keyed by (role, text): the same sentence can be an anchor in
# one triplet and a negative in another, and the prefixed arm gives those two
# different vectors on purpose.
_Vectors = dict[tuple[str, str], np.ndarray]


def _margins(triplets: list[dict[str, str]], vectors: _Vectors, negative: str) -> Any:
    """cos(anchor, positive) - cos(anchor, negative), one per triplet."""
    return [
        _cosine(vectors[_QUERY, row["anchor"]], vectors[_DOCUMENT, row["positive"]])
        - _cosine(vectors[_QUERY, row["anchor"]], vectors[_DOCUMENT, row[negative]])
        for row in triplets
    ]


def _accuracy_and_margin(margins: list[float]) -> tuple[float, float]:
    """Share of triplets the arm got right, and by how much on average."""
    return (
        round(sum(1 for margin in margins if margin > 0) / len(margins), 4),
        round(statistics.fmean(margins), 4),
    )


def _score_triplets(
    triplets: list[dict[str, str]], vectors: _Vectors
) -> dict[str, Any]:
    """Accuracy and margin against each negative, for one arm on one dataset."""
    scored: dict[str, Any] = {
        "triplets": len(triplets),
        "positive_cosine": round(
            statistics.fmean(
                _cosine(
                    vectors[_QUERY, row["anchor"]], vectors[_DOCUMENT, row["positive"]]
                )
                for row in triplets
            ),
            4,
        ),
    }
    for negative in _NEGATIVES:
        prefix = negative.removesuffix("_negative")
        scored[f"{prefix}_negative_cosine"] = round(
            statistics.fmean(
                _cosine(
                    vectors[_QUERY, row["anchor"]], vectors[_DOCUMENT, row[negative]]
                )
                for row in triplets
            ),
            4,
        )
        accuracy, margin = _accuracy_and_margin(_margins(triplets, vectors, negative))
        scored[f"{prefix}_accuracy"] = accuracy
        scored[f"{prefix}_margin"] = margin
    return scored


def _by_negative_kind(
    triplets: list[dict[str, str]], vectors: _Vectors
) -> list[dict[str, Any]]:
    """Hard-negative accuracy split by how the negative was written.

    An inversion reuses almost every word of the anchor and reverses the claim; an
    adjacent fact reuses the vocabulary and states something else. They are
    different kinds of hard, and averaging them hides which one an arm fails.
    """
    breakdown = []
    for kind in sorted({row["hard_negative_kind"] for row in triplets}):
        matching = [row for row in triplets if row["hard_negative_kind"] == kind]
        accuracy, margin = _accuracy_and_margin(
            _margins(matching, vectors, "hard_negative")
        )
        breakdown.append(
            {
                "kind": kind,
                "triplets": len(matching),
                "hard_accuracy": accuracy,
                "hard_margin": margin,
            }
        )
    return breakdown


def _corpus_similarity(sentences: list[str], vectors: np.ndarray) -> dict[str, Any]:
    """Cosine over every pair of corpus sentences, against the shipped thresholds.

    The two thresholds in this system are absolute cosine cut-offs, so what they
    admit depends entirely on where this corpus already sits. ``share_above_*`` is
    the fraction of *arbitrary* sentence pairs each one lets through: the closer
    that is to 1, the less the threshold is separating.
    """
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    normalised = np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)
    similarities = normalised @ normalised.T
    # Upper triangle only: each unordered pair once, and no sentence with itself.
    pairs = similarities[np.triu_indices(len(sentences), k=1)]
    return {
        "sentences": len(sentences),
        "pairs": int(pairs.size),
        "mean": round(float(pairs.mean()), 4),
        "p50": round(float(np.percentile(pairs, 50)), 4),
        "p90": round(float(np.percentile(pairs, 90)), 4),
        "max": round(float(pairs.max()), 4),
        "share_above_answer_match": round(
            float((pairs >= ANSWER_MATCH_THRESHOLD).mean()), 4
        ),
        "share_above_support": round(float((pairs >= SUPPORT_THRESHOLD).mean()), 4),
    }


def _roled_texts(
    triplets_by_dataset: dict[str, list[dict[str, str]]],
) -> dict[str, list[str]]:
    """Every triplet text, de-duplicated per role, in a stable order."""
    by_role: dict[str, dict[str, None]] = {_QUERY: {}, _DOCUMENT: {}}
    for rows in triplets_by_dataset.values():
        for row in rows:
            by_role[_QUERY].setdefault(row["anchor"], None)
            for field in ("positive", *_NEGATIVES):
                by_role[_DOCUMENT].setdefault(row[field], None)
    return {role: list(texts) for role, texts in by_role.items()}


def _lookup(arm: _Arm, by_role: dict[str, list[str]]) -> _Vectors:
    """Embed every text in the role it plays, keyed by (role, text)."""
    return {
        (role, text): np.asarray(vector, dtype=float)
        for role, texts in by_role.items()
        for text, vector in zip(texts, arm.vectors(texts, role))
    }


def _run() -> dict[str, Any]:
    raw = json.loads(_TRIPLETS_PATH.read_text(encoding="utf-8"))
    triplets_by_dataset = {name: raw[name] for name in _DATASETS}
    by_role = _roled_texts(triplets_by_dataset)
    sentences = [
        sentence
        for name in _DATASETS
        for page in _load_pages(_DATA_DIR / name)
        for sentence in split_sentences(page)
    ]

    embedder = OllamaEmbedder.from_env()
    arms: dict[str, _Arm] = {
        embedder._model: _PlainArm(embedder),
        f"{embedder._model}+task-prefix": _PrefixedArm(embedder),
        "lexical-tfidf": _LexicalArm(
            [text for texts in by_role.values() for text in texts] + sentences
        ),
        "random": _RandomArm(_SEED, _RANDOM_DIMS),
    }

    datasets: list[dict[str, Any]] = [
        {"dataset": name, "triplets": len(rows), "arms": []}
        for name, rows in triplets_by_dataset.items()
    ]
    pooled = [row for rows in triplets_by_dataset.values() for row in rows]
    overall: list[dict[str, Any]] = []
    corpus: list[dict[str, Any]] = []

    for name, arm in arms.items():
        vectors = _lookup(arm, by_role)
        for entry, rows in zip(datasets, triplets_by_dataset.values()):
            entry["arms"].append({"arm": name, **_score_triplets(rows, vectors)})
        overall.append(
            {
                "arm": name,
                **_score_triplets(pooled, vectors),
                "by_hard_negative_kind": _by_negative_kind(pooled, vectors),
            }
        )
        corpus.append(
            {
                "arm": name,
                **_corpus_similarity(
                    sentences,
                    np.asarray(arm.vectors(sentences, _DOCUMENT), dtype=float),
                ),
            }
        )

    return {
        "embedding_model": embedder._model,
        "arms": list(arms),
        "seed": _SEED,
        "thresholds": {
            "answer_match": ANSWER_MATCH_THRESHOLD,
            "support": SUPPORT_THRESHOLD,
        },
        "datasets": datasets,
        "overall": overall,
        "corpus_similarity": corpus,
    }


def _print_table(payload: dict[str, Any]) -> None:
    header = (
        f"{'arm':<28} {'trip':>5} {'pos_cos':>8} {'hard_acc':>9} {'hard_mrg':>9} "
        f"{'easy_acc':>9} {'easy_mrg':>9}"
    )

    def rows(entries: list[dict[str, Any]]) -> None:
        print(header)
        print("-" * len(header))
        for row in entries:
            print(
                f"{row['arm']:<28} {row['triplets']:>5} {row['positive_cosine']:>8.3f} "
                f"{row['hard_accuracy']:>9.3f} {row['hard_margin']:>9.3f} "
                f"{row['easy_accuracy']:>9.3f} {row['easy_margin']:>9.3f}"
            )

    for dataset in payload["datasets"]:
        print(f"\nembedding quality - {dataset['dataset']}")
        rows(dataset["arms"])

    print("\nembedding quality - both datasets pooled")
    rows(payload["overall"])

    print("\nhard negatives by kind")
    kind_header = f"{'arm':<28} {'kind':<15} {'trip':>5} {'acc':>7} {'margin':>8}"
    print(kind_header)
    print("-" * len(kind_header))
    for row in payload["overall"]:
        for kind in row["by_hard_negative_kind"]:
            print(
                f"{row['arm']:<28} {kind['kind']:<15} {kind['triplets']:>5} "
                f"{kind['hard_accuracy']:>7.3f} {kind['hard_margin']:>8.3f}"
            )

    thresholds = payload["thresholds"]
    print(
        f"\ncorpus sentence-pair similarity "
        f"(answer_match {thresholds['answer_match']}, "
        f"support {thresholds['support']})"
    )
    pair_header = (
        f"{'arm':<28} {'pairs':>6} {'mean':>7} {'p50':>7} {'p90':>7} {'max':>7} "
        f"{'>=match':>8} {'>=supp':>8}"
    )
    print(pair_header)
    print("-" * len(pair_header))
    for row in payload["corpus_similarity"]:
        print(
            f"{row['arm']:<28} {row['pairs']:>6} {row['mean']:>7.3f} "
            f"{row['p50']:>7.3f} {row['p90']:>7.3f} {row['max']:>7.3f} "
            f"{row['share_above_answer_match']:>8.3f} "
            f"{row['share_above_support']:>8.3f}"
        )


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
