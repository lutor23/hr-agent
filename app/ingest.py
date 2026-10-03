"""Embed the policy corpus and upsert it into a persistent ChromaDB collection.

Usage: python -m app.ingest [--corpus ./corpus] [--db ./chroma_db] [--reset] [--smoke]
"""

import argparse  # noqa: I001  (import order below is deliberate)
import threading

# app.config must be imported BEFORE chromadb: it sets ANONYMIZED_TELEMETRY=False,
# which chromadb reads at import time. Do not let an import sorter reorder this block.
from app import config
import chromadb
from chromadb.config import Settings

from app.loaders import load_corpus

SMOKE_QUERIES = {
    "How much PTO do I get per year?": "POL-HR-001",
    "Can I work remotely from another state?": "POL-HR-002",
    "How do I get reimbursed for a business trip?": "POL-HR-003",
    "Which medical plans does the company offer?": "POL-HR-004",
    "How long is parental leave?": "POL-HR-010",
    "How often are performance reviews conducted?": "POL-HR-011",
    "What is Acme Corp's gift and entertainment policy?": "POL-HR-017",
}


# Chunks embedded per upsert() call during ingest. The first real Render deploy was
# OOM-killed (512Mi limit) embedding all 97 chunks (the corpus size at the time) in
# one batch: measured locally, a single large batch peaks near 900MB regardless of
# embedding library, because onnxruntime's/torch's scratch memory for a batch scales
# with its size. Below batch=4 the peak stops shrinking much (~300MB floor: onnxruntime's
# own fixed overhead) - so 4 is picked for reasonable ingest speed, not because it's the
# minimum. Still correct after the corpus grew (177 chunks as of the Day 13 corpus
# expansion) since batching bounds peak memory per-call, independent of total chunk count.
# Not user-configurable: this is a memory-budget constant, not a deployment setting.
INGEST_BATCH_SIZE = 4


def get_embedding_function():
    # Imported here, not at module level: chromadb.utils.embedding_functions pulls in
    # onnxruntime as an import-time side effect regardless of which class you use, so
    # a top-level import would load it even in count_chunks()'s codepath, which must
    # not (see count_chunks()'s docstring). Deferring the import to inside this
    # function, which only get_collection() calls, keeps that guarantee.
    from chromadb.utils import embedding_functions

    # ONNXMiniLM_L6_V2 (bundled with chromadb) implements the same all-MiniLM-L6-v2
    # model as SentenceTransformerEmbeddingFunction, but via onnxruntime instead of
    # torch: no torch/sentence-transformers import, ~330MB lower baseline RSS
    # (measured: torch construction alone uses ~470MB before embedding anything; the
    # first real Render deploy needed every MB of that back to fit in 512Mi). CPU
    # provider is forced explicitly rather than auto-detected, since auto-detection
    # can pick a provider (e.g. CoreML on Apple Silicon) with very different, even
    # unbounded-looking, memory behavior from what a Linux deploy target will use.
    #
    # Redirect its model-cache location from the default Path.home()/.cache/chroma
    # to somewhere under this project's own root. Found live (Day 14, alongside the
    # build-time-ingest fix): Render's build step and runtime container do NOT share
    # $HOME's cache - CHROMA_PERSIST_DIR (already pointed at a path under the project
    # root) correctly persisted the ingested index from build to runtime, but the
    # 79MB ONNX model archive, cached under the default Path.home() location, was
    # still being re-downloaded from S3 on every runtime process start. Overriding
    # the class attribute before construction (there's no constructor parameter for
    # this) means the model downloaded once during the build step's --smoke run is
    # already on disk when the runtime process starts.
    embedding_functions.ONNXMiniLM_L6_V2.DOWNLOAD_PATH = (
        config.ROOT / ".onnx_model_cache" / embedding_functions.ONNXMiniLM_L6_V2.MODEL_NAME
    )
    return embedding_functions.ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])


def get_client(db_path: str = config.CHROMA_PERSIST_DIR):
    # chromadb 0.5.x telemetry is broken against current posthog; it only logs errors.
    return chromadb.PersistentClient(path=db_path, settings=Settings(anonymized_telemetry=False))


# get_collection()'s cache (below) and get_ready_collection()'s build-once check both
# need one shared Collection object per db_path, not a fresh one per call — two
# *separate* chromadb Collection/PersistentClient instances against the same on-disk
# path aren't guaranteed to see each other's writes immediately (a second instance's
# .count() can still read stale/0 right after a first instance's .upsert() commits),
# which let concurrent get_ready_collection() calls each pass their empty-index check
# and both call ingest() — caught by a concurrency test, not by inspection. One shared
# object removes the cross-instance staleness question entirely: every caller reads
# and writes through the exact same in-memory Collection. The lock protects the
# cache's construction (get_collection) and the check-and-build (get_ready_collection)
# across threads; it's a plain threading.Lock rather than an asyncio one because
# FastMCP calls sync tools directly on the event loop (confirmed in its source - no
# threadpool) while mcp/server.py's background build runs via anyio.to_thread, a real
# OS thread, so the lock has to work correctly across both.
_collection_cache: dict[str, "chromadb.api.models.Collection.Collection"] = {}
# RLock, not Lock: get_ready_collection() holds this while calling ingest(), which
# itself calls get_collection() (to (re)fetch the collection it upserts into), which
# acquires this same lock again - on the same thread, since neither anyio.to_thread
# nor FastMCP's direct sync-tool dispatch hands the call to a different thread partway
# through. A plain Lock would deadlock there; RLock allows a thread to re-enter a lock
# it already holds.
_cache_lock = threading.RLock()


def get_collection(db_path: str = config.CHROMA_PERSIST_DIR):
    """Loads the embedding function in THIS process (once; cached per db_path after
    that). Called by ingest()/smoke() (which are meant to load it) and by
    get_ready_collection() below. Don't call this from the FastAPI process
    (app/main.py) — use count_chunks() there, which never loads it at all."""
    with _cache_lock:
        if db_path not in _collection_cache:
            _collection_cache[db_path] = get_client(db_path).get_or_create_collection(
                name=config.COLLECTION_NAME,
                embedding_function=get_embedding_function(),
                metadata={"hnsw:space": "cosine"},
            )
        return _collection_cache[db_path]


def get_ready_collection(db_path: str = config.CHROMA_PERSIST_DIR):
    """get_collection(), auto-ingesting first if the index is empty.

    Only app/retriever.py (i.e. only the MCP server subprocess) calls this. That
    keeps embedding-model ownership in exactly one process: the FastAPI process
    (app/main.py) never loads it at all, it only ever calls count_chunks() below.
    Loading it in *both* processes (FastAPI eagerly at startup, MCP subprocess
    lazily on first search) is what OOM-killed the first real Render deploy — two
    independent onnxruntime sessions at once, each with the same ~150-200MB
    overhead, on top of each process's own baseline.
    """
    collection = get_collection(db_path)
    if collection.count() == 0:
        with _cache_lock:
            if collection.count() == 0:  # re-check: another caller may have just built it
                ingest(str(config.CORPUS_DIR), db_path)
    return collection


def count_chunks(db_path: str = config.CHROMA_PERSIST_DIR) -> int:
    """Indexed chunk count (0 if not ingested yet). Deliberately skips the embedding
    function, so calling it never loads onnxruntime in this process. This is the
    ONLY ingest.py function app/main.py (the FastAPI process) may call — see
    get_ready_collection()'s docstring for why."""
    try:
        return get_client(db_path).get_collection(config.COLLECTION_NAME).count()
    except Exception:  # collection doesn't exist: ingest hasn't been run
        return 0


def ingest(corpus: str, db_path: str, reset: bool = False) -> int:
    if reset:
        try:
            get_client(db_path).delete_collection(config.COLLECTION_NAME)
        except Exception:
            pass  # collection did not exist yet
        # Drop the cached Collection object too: it still refers to whatever was just
        # deleted, and get_collection() would otherwise hand callers that stale object
        # instead of building a fresh one against the (now empty or nonexistent) store.
        with _cache_lock:
            _collection_cache.pop(db_path, None)
    collection = get_collection(db_path)
    chunks = load_corpus(corpus)
    # Batched (see INGEST_BATCH_SIZE) rather than one upsert() for the whole corpus:
    # embedding a large batch in one call is what OOM-killed the first real deploy.
    for i in range(0, len(chunks), INGEST_BATCH_SIZE):
        batch = chunks[i : i + INGEST_BATCH_SIZE]
        collection.upsert(
            ids=[c.chunk_id for c in batch],
            documents=[c.embed_text for c in batch],
            metadatas=[c.metadata() for c in batch],
        )
    return collection.count()


def smoke(db_path: str) -> bool:
    collection = get_collection(db_path)
    ok = True
    for query, expected in SMOKE_QUERIES.items():
        res = collection.query(query_texts=[query], n_results=3)
        top_docs = [m["doc_id"] for m in res["metadatas"][0]]
        hit = expected in top_docs
        ok &= hit
        print(f"{'PASS' if hit else 'FAIL'}  {query!r} -> {top_docs} (expected {expected})")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(config.CORPUS_DIR))
    parser.add_argument("--db", default=config.CHROMA_PERSIST_DIR)
    parser.add_argument("--reset", action="store_true", help="drop the collection first")
    parser.add_argument("--smoke", action="store_true", help="run retrieval smoke test")
    args = parser.parse_args()

    count = ingest(args.corpus, args.db, args.reset)
    print(f"Indexed {count} chunks into {args.db}")
    if args.smoke and not smoke(args.db):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
