"""Storage-index eval for the storage stage (``REQ-EVL-02``).

The other evals in this directory avoid the database on purpose — the retrieval
eval ranks chunks in memory, the faithfulness eval retrieves in-process — because
for them Postgres is plumbing. For this one it is the subject, so this is the eval
that has to connect.

The storage stage's quality claim is in ``db/schema.sql``: chunks are searched
through an **HNSW** index over cosine distance. HNSW is an *approximate*
nearest-neighbour index — faster than scanning every row precisely because it is
allowed to miss things, and nothing above it can tell when it does, since a chunk
the index skipped looks exactly like a chunk that was never relevant. Retrieval
quality therefore has a ceiling set here, underneath every number the retrieval and
generation evals report.

**An index is only approximate if the planner actually uses it**, and whether it
does depends on how ``search_chunks`` was called. So the eval runs all three shapes
the application uses, and records the plan for each:

====================  ==========================================  ================
shape                 how the query is parameterised              called by
====================  ==========================================  ================
``role_only``         ``document_id`` and ``chunking_strategy``    ``/retrieve``,
                      both NULL — search everything the role       ``/answer``
                      may read
``strategy``          ``chunking_strategy`` set, ``document_id``  ``/retrieve`` and
                      NULL — one strategy, every document         ``/answer`` with
                                                                  a strategy filter
``scoped``            both set — one strategy of one document     ``/evaluate``
====================  ==========================================  ================

**The comparison is exact search, and there are four arms per shape:**

====================  ==========================================  ================
arm                   how it is run                               what it says
====================  ==========================================  ================
``exact``             index scans off, so Postgres must scan and  the ground truth
                      sort — the exact answer by construction     every arm is
                                                                  scored against
``planner``           plain defaults                              what the
                                                                  application
                                                                  actually gets
``hnsw``              ``enable_sort = off``, which leaves the     what the index
                      index as the only ordered path, with        itself costs,
                      ``ef_search`` swept                         when it is used
``random``            k rows drawn at random                      the control
====================  ==========================================  ================

``planner`` and ``hnsw`` are separate arms because they turned out to be different
things. **The planner does not choose the index here** — it gathers the role's
chunks through the ``document_id`` foreign key and sorts them, which is exact, and
which the planner costs as cheap because a plan's cost does not include detoasting
the 3 kB vector it is about to compare. So the shipped search is exact today, and
the HNSW index is paying for itself on every insert and earning nothing on any
read. ``uses_hnsw_index`` records that per shape rather than leaving it to be
assumed, and the ``hnsw`` arm forces the index anyway, so the recall it *would*
cost is measured against the day the planner changes its mind.

**And forcing it costs nothing either — at this size.** Every ``ef_search`` from 1
to 100 returns the exact top-k, on every shape. That is a fact about the corpus
before it is a fact about HNSW: a few thousand vectors is a small graph, and greedy
search on a small graph does not get lost. The ``random`` arm is what makes those
1.000s readable — it scores 0.00–0.02 on the same comparison, so the metric can
plainly tell a good answer from a bad one and is not stuck reporting success. Read
the result as **the index is costing this project no recall, and earning it no
speed either**. Both change with scale; finding where means raising
``_ROWS_PER_ROLE`` by an order of magnitude and accepting the longer run.

**``ef_search`` is swept, because it is the dial.** HNSW trades recall for speed
through how much of the graph it explores, and pgvector exposes that as
``hnsw.ef_search`` (default 40). A single value would report one point on a curve
as though it were a property of the index. Latency sits next to recall throughout,
because recall bought at any price is not a trade-off anyone chose.

**The table is filled on purpose, and not only with rows the query may read.**
The two sample documents chunk into a few dozen rows, which is a table nothing can
be learned from: an index over it is trivially exact and a scan over it is
trivially fast. So the real chunk embeddings are replicated with Gaussian noise
into a few thousand rows, which keeps the clustered geometry of real text (variants
sit near their base chunk); the achieved mean cosine to the base is reported, so
the corpus describes itself rather than asking to be trusted. This is still a small
index by ANN standards — see the recall result above — and that is the honest
ceiling on what one run can say. Half the rows go under a **second access role**
the queries may not read, because the role filter is applied *after* the index in
the forced ``role_only`` plan — on a single-role table that filter is free, and the
eval would be measuring a table no deployment has.

Rows are written through the **shipped** ``PostgresStorage``, one at a time,
exactly as ``/process`` writes them, so the ingest throughput reported here is the
real one and not a batched approximation of it. The table is then analysed, so the
planner is costing the search against the rows that are actually there rather than
against the ones it last looked at — a running system gets that from autovacuum,
and an eval that loads thousands of rows and queries seconds later has to ask. It
did not change which plan was chosen (the sort wins either way), but a plan chosen
on statistics the eval itself invalidated would not have been worth recording.

Nothing is left behind: the eval writes under document names and access roles of
its own and deletes them (chunks cascade) when it finishes. No vector reaches the
artifact — the results hold metrics only, never embeddings.

**Read the latencies as a shape, not as digits.** Recall, the plans and
``uses_hnsw_index`` reproduce exactly; the millisecond columns do not, and move by
a factor of two or more between runs of the same code on the same rows. They are
here to show that no arm is buying its recall with time, not to rank arms against
each other.

Run it with the compose stack up, from ``backend/``:
    DATABASE_URL=postgresql://rag:rag@localhost:5435/rag \\
      OLLAMA_BASE_URL=http://localhost:11434 \\
      uv run python -m evals.storage_index_eval

It needs both a running Ollama (to embed) and a live PostgreSQL/pgvector — the
same pairing the ``integration`` test tier needs. Results are written to
``evals/results/storage_index.json`` and are a regenerable artifact, not a one-off
screenshot.
"""

import json
import random
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
from pgvector import Vector

from dtos.requests import FixedSizeChunkingRequest
from dtos.responses import Chunk, RetrievedChunk
from evals.fixed_size_chunking_eval import _load_pages
from services.chunking import FixedSizeChunker
from services.embedding import Embedder, OllamaEmbedder
from services.storage import PostgresStorage
from services.storage.postgres import _SEARCH_CHUNKS

_DATA_DIR = Path(__file__).parent / "data"
_QA_PATH = _DATA_DIR / "sample_qa.json"
_RESULTS_PATH = Path(__file__).parent / "results" / "storage_index.json"

# Flat prose first, then a document that marks up its own structure -- the same
# two fixtures the other evals use, so every eval talks about one corpus.
_DATASETS = ["sample.txt", "structured_sample.txt"]

# The structure-blind baseline, so the corpus is not shaped by a chunking strategy
# that happens to suit one document. Which strategy chunks best is REQ-EVL-03's
# question, not this one.
_CHUNK_SIZE = 64

# Rows per access role: one population the queries may read and one they may not.
# Big enough that neither a scan nor an index over it is trivial, small enough that
# a run stays in minutes -- the shipped ingest path writes one row per transaction
# (~56 rows/s), so this constant sets the run time almost by itself. Deliberately a
# constant and not a parameter: raise it here to ask the scale question at a bigger
# size, and expect the run to grow in proportion.
_ROWS_PER_ROLE = 3000

# Per-dimension noise added to a base vector to make one variant. Chosen to land
# variants near their base rather than on top of it; the achieved cosine is
# measured and reported rather than assumed.
_NOISE_SIGMA = 0.02

# ef_search values swept, spanning far below the default to well above it: a sweep
# that only covers the safe range cannot say whether the default is safe.
_EF_SEARCH_VALUES = [1, 5, 10, 40, 100]
_DEFAULT_EF_SEARCH = 40

# Cut-offs to report at. Recall is defined *at* a k, and an index's misses show up
# differently as the cut-off moves.
_TOP_K_VALUES = [3, 5, 10]

_SEED = 20260902

# The eval's own documents. Both roles are its own, so nothing it writes can be
# confused with, or returned alongside, anything else in a shared database. The
# second exists only to put rows in the index that the queries may not read.
_DOCUMENT_NAME = "eval:storage-index"
_ACCESS_ROLE = "eval-storage-index"
_OTHER_DOCUMENT_NAME = "eval:storage-index-other-role"
_OTHER_ACCESS_ROLE = "eval-storage-index-other"
_STRATEGY = "fixed"

# The three ways the application parameterises search_chunks. ``document`` says
# whether the search is confined to one document id, which is only known once the
# eval's document has been created.
_SHAPES: dict[str, dict[str, Any]] = {
    "role_only": {"chunking_strategy": None, "document": False},
    "strategy": {"chunking_strategy": _STRATEGY, "document": False},
    "scoped": {"chunking_strategy": _STRATEGY, "document": True},
}

# The index the schema creates; its name appearing in a plan is what says it was
# used.
_HNSW_INDEX = "chunks_embedding_hnsw_idx"

# Removes the eval's documents; chunks go with them through the FK cascade.
# Storage has no delete-document method -- nothing in the app deletes a document
# -- so this is the eval's own housekeeping and stays here rather than widening
# the service's surface for a caller that does not exist.
_DELETE_DOCUMENT = "DELETE FROM documents WHERE name = %s AND access_role = %s"

# Refreshes the planner's statistics after the bulk load, so the plan recorded
# below is costed against the rows that are there rather than the ones the planner
# last looked at. A running system gets this from autovacuum; an eval that loads
# thousands of rows and queries seconds later has to ask. It does not change which
# plan wins here -- the sort does, either way -- but a plan chosen on statistics
# the eval itself invalidated would not be worth recording.
_ANALYZE = "ANALYZE chunks"


def _parameters(shape: str, document_id: int) -> dict[str, Any]:
    """The ``search_chunks`` filter arguments for one shape."""
    return {
        "chunking_strategy": _SHAPES[shape]["chunking_strategy"],
        "document_id": document_id if _SHAPES[shape]["document"] else None,
    }


def _base_chunks(embedder: Embedder) -> tuple[list[str], np.ndarray]:
    """Chunk both fixtures at the fixed window and embed them once."""
    texts = [
        chunk
        for name in _DATASETS
        for chunk in FixedSizeChunker(
            FixedSizeChunkingRequest(chunk_size=_CHUNK_SIZE)
        ).chunk(_load_pages(_DATA_DIR / name))
    ]
    return texts, np.asarray(embedder.embed(texts), dtype=float)


def _unit(vectors: np.ndarray) -> np.ndarray:
    """Row-wise unit vectors; a zero row is left as zeros rather than NaN."""
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


def _grow_corpus(
    base: np.ndarray, rows: int, rng: np.random.Generator
) -> tuple[np.ndarray, list[int], float]:
    """Replicate the base vectors with noise until the table is worth indexing.

    Returns the corpus, the index of the base chunk each row came from (so its
    text can be stored with it), and the mean cosine between a row and its base —
    the number that says how tight the resulting clusters actually are.
    """
    sources = [index % len(base) for index in range(rows)]
    unit_base = _unit(base)[sources]
    corpus = _unit(unit_base + rng.normal(0.0, _NOISE_SIGMA, size=unit_base.shape))
    return corpus, sources, float(np.sum(corpus * unit_base, axis=1).mean())


def _ingest(
    storage: PostgresStorage,
    name: str,
    access_role: str,
    texts: list[str],
    sources: list[int],
    corpus: np.ndarray,
) -> tuple[int, float]:
    """Write every row through the shipped one-chunk-at-a-time path.

    ``create_document`` clears whatever a previous run left, so the eval is
    re-runnable without piling up rows. Returns the document id and the wall-clock
    seconds the write took — the throughput of the real path, HNSW index
    maintenance included.
    """
    document_id = storage.create_document(name, access_role)
    started = time.perf_counter()
    for index, (source, vector) in enumerate(zip(sources, corpus)):
        chunk = Chunk.from_page(1, texts[source]).model_copy(
            update={"embedding": [float(value) for value in vector]}
        )
        storage.insert_chunk(document_id, _STRATEGY, index, chunk)
    return document_id, time.perf_counter() - started


def _set(storage: PostgresStorage, statement: str) -> None:
    """Run a session-level SET on the connection the searches will use.

    ``hnsw.ef_search`` and the planner switches are per-session settings, so they
    have to be set on the *same* connection ``search_chunks`` runs on — which means
    using the storage service's own connection rather than opening another one.
    """
    with storage._conn.cursor() as cursor:
        cursor.execute(statement)


def _plan(
    storage: PostgresStorage, query: list[float], shape: str, document_id: int
) -> str:
    """The plan for the shipped search SQL in one shape, as a single string.

    Recorded so the artifact can show which shape reached the index and which did
    not — otherwise a shape that quietly sorted every row would report perfect
    recall and be read as a well-behaved index.
    """
    with storage._conn.cursor() as cursor:
        cursor.execute(
            f"EXPLAIN {_SEARCH_CHUNKS}",
            {
                "query": Vector(query),
                "access_role": _ACCESS_ROLE,
                "top_k": max(_TOP_K_VALUES),
                **_parameters(shape, document_id),
            },
        )
        # The query vector is echoed into the Sort/Order By line; it is 768 floats
        # long and says nothing, so plan lines are truncated.
        return " | ".join(row[0].strip()[:80] for row in cursor.fetchall())


def _search(
    storage: PostgresStorage,
    query: list[float],
    top_k: int,
    shape: str,
    document_id: int,
) -> tuple[list[int], float]:
    """One search, returning the retrieved chunk indices and its latency in ms."""
    started = time.perf_counter()
    results: list[RetrievedChunk] = storage.search_chunks(
        query_embedding=query,
        access_role=_ACCESS_ROLE,
        top_k=top_k,
        **_parameters(shape, document_id),
    )
    latency = (time.perf_counter() - started) * 1000.0
    return [chunk.chunk_index for chunk in results], latency


def _run_queries(
    storage: PostgresStorage,
    queries: list[list[float]],
    top_k: int,
    shape: str,
    document_id: int,
) -> tuple[list[list[int]], list[float]]:
    """Run every query at one cut-off, collecting results and latencies."""
    results, latencies = [], []
    for query in queries:
        retrieved, latency = _search(storage, query, top_k, shape, document_id)
        results.append(retrieved)
        latencies.append(latency)
    return results, latencies


def _score(
    retrieved: list[list[int]], exact: list[list[int]], latencies: list[float]
) -> dict[str, Any]:
    """Recall against exact search, top-1 agreement, and the latency it cost."""
    recalls = [
        len(set(got) & set(truth)) / len(truth) if truth else 0.0
        for got, truth in zip(retrieved, exact)
    ]
    top1 = [
        1.0 if got and truth and got[0] == truth[0] else 0.0
        for got, truth in zip(retrieved, exact)
    ]
    ordered = sorted(latencies)
    return {
        "recall_vs_exact": round(statistics.fmean(recalls), 4),
        "top1_agreement": round(statistics.fmean(top1), 4),
        "mean_latency_ms": round(statistics.fmean(latencies), 2),
        "p95_latency_ms": round(
            ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 2
        ),
    }


def _run_shape(
    storage: PostgresStorage,
    queries: list[list[float]],
    shape: str,
    document_id: int,
    shuffler: random.Random,
) -> dict[str, Any]:
    """Every arm for one call shape, all scored against the same exact answer."""

    def sweep(
        arm: str, ef_search: int | None, exact: dict[int, list[list[int]]]
    ) -> None:
        for top_k in _TOP_K_VALUES:
            results, latencies = _run_queries(
                storage, queries, top_k, shape, document_id
            )
            runs.append(
                {
                    "arm": arm,
                    "ef_search": ef_search,
                    "top_k": top_k,
                    **_score(results, exact.get(top_k, results), latencies),
                }
            )
            exact.setdefault(top_k, results)

    runs: list[dict[str, Any]] = []

    # Exact first: it is what every other arm is scored against, and it is what
    # the planner does once index scans are off.
    _set(storage, "SET enable_indexscan = off")
    _set(storage, "SET enable_bitmapscan = off")
    exact_plan = _plan(storage, queries[0], shape, document_id)
    exact: dict[int, list[list[int]]] = {}
    sweep("exact", None, exact)
    _set(storage, "SET enable_indexscan = on")
    _set(storage, "SET enable_bitmapscan = on")

    # What the application actually gets, at the shipped ef_search.
    _set(storage, f"SET hnsw.ef_search = {_DEFAULT_EF_SEARCH}")
    planner_plan = _plan(storage, queries[0], shape, document_id)
    sweep("planner", _DEFAULT_EF_SEARCH, exact)

    # Force the index: with sorting disabled it is the only path that can return
    # rows already in distance order, so this is the index measuring itself.
    _set(storage, "SET enable_sort = off")
    forced_plan = _plan(storage, queries[0], shape, document_id)
    for ef_search in _EF_SEARCH_VALUES:
        _set(storage, f"SET hnsw.ef_search = {ef_search}")
        sweep("hnsw", ef_search, exact)
    _set(storage, "SET enable_sort = on")

    # The control: k rows drawn at random from the same population, scored the
    # same way. It has no latency to report -- nothing was searched.
    for top_k in _TOP_K_VALUES:
        random_results = [
            shuffler.sample(range(_ROWS_PER_ROLE), top_k) for _ in queries
        ]
        runs.append(
            {
                "arm": "random",
                "ef_search": None,
                "top_k": top_k,
                **_score(random_results, exact[top_k], [0.0]),
                "mean_latency_ms": None,
                "p95_latency_ms": None,
            }
        )

    return {
        "shape": shape,
        "parameters": _parameters(shape, document_id),
        "uses_hnsw_index": _HNSW_INDEX in planner_plan,
        "forced_uses_hnsw_index": _HNSW_INDEX in forced_plan,
        "plans": {
            "planner": planner_plan,
            "forced_hnsw": forced_plan,
            "exact": exact_plan,
        },
        "runs": runs,
    }


def _run() -> dict[str, Any]:
    embedder = OllamaEmbedder.from_env()
    rng = np.random.default_rng(_SEED)
    shuffler = random.Random(_SEED)

    texts, base = _base_chunks(embedder)
    corpus, sources, mean_cosine = _grow_corpus(base, _ROWS_PER_ROLE, rng)
    other, other_sources, _ = _grow_corpus(base, _ROWS_PER_ROLE, rng)

    qa_by_dataset = json.loads(_QA_PATH.read_text(encoding="utf-8"))
    questions = [pair["question"] for name in _DATASETS for pair in qa_by_dataset[name]]
    queries = embedder.embed(questions)

    storage = PostgresStorage.connect()
    try:
        document_id, ingest_seconds = _ingest(
            storage, _DOCUMENT_NAME, _ACCESS_ROLE, texts, sources, corpus
        )
        # Rows the queries may not read, so the role filter in the plan has
        # something to filter.
        _ingest(
            storage,
            _OTHER_DOCUMENT_NAME,
            _OTHER_ACCESS_ROLE,
            texts,
            other_sources,
            other,
        )
        _set(storage, _ANALYZE)
        shapes = [
            _run_shape(storage, queries, shape, document_id, shuffler)
            for shape in _SHAPES
        ]
    finally:
        with storage._conn.cursor() as cursor:
            cursor.execute(_DELETE_DOCUMENT, (_DOCUMENT_NAME, _ACCESS_ROLE))
            cursor.execute(_DELETE_DOCUMENT, (_OTHER_DOCUMENT_NAME, _OTHER_ACCESS_ROLE))

    return {
        "embedding_model": embedder._model,
        "index": "hnsw (vector_cosine_ops)",
        "seed": _SEED,
        "default_ef_search": _DEFAULT_EF_SEARCH,
        "corpus": {
            "base_chunks": len(texts),
            "chunk_size": _CHUNK_SIZE,
            "rows_in_role": _ROWS_PER_ROLE,
            "rows_other_role": _ROWS_PER_ROLE,
            "noise_sigma": _NOISE_SIGMA,
            "mean_cosine_to_base": round(mean_cosine, 4),
            "ingest_seconds": round(ingest_seconds, 2),
            "rows_per_second": round(_ROWS_PER_ROLE / ingest_seconds, 1),
        },
        "queries": len(questions),
        "shapes": shapes,
    }


def _print_table(payload: dict[str, Any]) -> None:
    corpus = payload["corpus"]
    print(
        f"\nstorage index - {corpus['rows_in_role']} rows in role + "
        f"{corpus['rows_other_role']} out of role, from {corpus['base_chunks']} "
        f"base chunks (mean cosine to base {corpus['mean_cosine_to_base']}, "
        f"{payload['queries']} queries, embeddings: {payload['embedding_model']})"
    )
    print(
        f"ingest: {corpus['ingest_seconds']}s for {corpus['rows_in_role']} rows, "
        f"one row per transaction ({corpus['rows_per_second']} rows/s)"
    )

    header = (
        f"{'arm':<8} {'ef':>5} {'k':>4} {'recall':>8} {'top1':>7} "
        f"{'mean_ms':>9} {'p95_ms':>9}"
    )
    for shape in payload["shapes"]:
        print(
            f"\nshape {shape['shape']} {shape['parameters']} - "
            f"planner uses hnsw index: {shape['uses_hnsw_index']}, "
            f"forced: {shape['forced_uses_hnsw_index']}"
        )
        print(f"  planner plan: {shape['plans']['planner']}")
        print(header)
        print("-" * len(header))
        for run in shape["runs"]:
            mean_ms, p95_ms = run["mean_latency_ms"], run["p95_latency_ms"]
            ef_search = "-" if run["ef_search"] is None else run["ef_search"]
            print(
                f"{run['arm']:<8} {ef_search:>5} {run['top_k']:>4} "
                f"{run['recall_vs_exact']:>8.3f} {run['top1_agreement']:>7.3f} "
                f"{'-' if mean_ms is None else f'{mean_ms:.2f}':>9} "
                f"{'-' if p95_ms is None else f'{p95_ms:.2f}':>9}"
            )


def main() -> None:
    payload = _run()
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _print_table(payload)
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
