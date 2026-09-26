"""Shared fixtures.

Most tests need the ChromaDB index. Build it once per session if it's missing so the
suite passes on a fresh checkout / CI runner without a manual `python -m app.ingest`.
"""

import pytest

from app import config, ingest


@pytest.fixture(scope="session", autouse=True)
def ensure_index_exists():
    if ingest.count_chunks() == 0:
        ingest.ingest(str(config.CORPUS_DIR), config.CHROMA_PERSIST_DIR)
