"""Embed the policy corpus and upsert it into a persistent ChromaDB collection.

Usage: python -m app.ingest [--corpus ./corpus] [--db ./chroma_db] [--reset] [--smoke]
"""

import argparse

from app import config  # sets ANONYMIZED_TELEMETRY=False before chromadb is imported

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from app.loaders import load_corpus

SMOKE_QUERIES = {
    "How much PTO do I get per year?": "POL-HR-001",
    "Can I work remotely from another state?": "POL-HR-002",
    "How do I get reimbursed for a business trip?": "POL-HR-003",
    "Which medical plans does the company offer?": "POL-HR-004",
    "How long is parental leave?": "POL-HR-010",
}


def get_embedding_function():
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )


def get_client(db_path: str = config.CHROMA_PERSIST_DIR):
    # chromadb 0.5.x telemetry is broken against current posthog; it only logs errors.
    return chromadb.PersistentClient(path=db_path, settings=Settings(anonymized_telemetry=False))


def get_collection(db_path: str = config.CHROMA_PERSIST_DIR):
    return get_client(db_path).get_or_create_collection(
        name=config.COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def ingest(corpus: str, db_path: str, reset: bool = False) -> int:
    if reset:
        try:
            get_client(db_path).delete_collection(config.COLLECTION_NAME)
        except Exception:
            pass  # collection did not exist yet
    collection = get_collection(db_path)
    chunks = load_corpus(corpus)
    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.embed_text for c in chunks],
        metadatas=[c.metadata() for c in chunks],
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
