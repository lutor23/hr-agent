"""Ingest tests: build a throwaway ChromaDB in tmp_path (never touches ./chroma_db)."""

import subprocess
import sys
import threading

import pytest

from app import config, ingest
from app.loaders import load_corpus


@pytest.fixture(scope="module")
def expected_count():
    return len(load_corpus(config.CORPUS_DIR))


@pytest.fixture(scope="module")
def db(tmp_path_factory, expected_count):
    path = str(tmp_path_factory.mktemp("chroma"))
    assert ingest.ingest(str(config.CORPUS_DIR), path, reset=True) == expected_count
    return path


def test_ingest_indexes_every_chunk(db, expected_count):
    assert ingest.count_chunks(db) == expected_count


def test_ingest_is_idempotent(db, expected_count):
    assert ingest.ingest(str(config.CORPUS_DIR), db) == expected_count  # upsert, no duplicates


def test_reset_rebuilds_from_scratch(db, expected_count):
    assert ingest.ingest(str(config.CORPUS_DIR), db, reset=True) == expected_count


def test_indexed_metadata_supports_citations(db):
    res = ingest.get_collection(db).get(ids=["POL-HR-001-000"], include=["metadatas", "documents"])
    meta = res["metadatas"][0]
    assert set(meta) == {"chunk_id", "doc_id", "title", "section", "source_file", "fmt"}
    assert meta["doc_id"] == "POL-HR-001" and res["documents"][0].startswith(f"{meta['title']} - {meta['section']}")


def test_count_chunks_is_zero_before_ingest(tmp_path):
    assert ingest.count_chunks(str(tmp_path / "never_ingested")) == 0


def test_count_chunks_never_constructs_the_embedding_function(monkeypatch, tmp_path):
    """The FastAPI process must stay light (free-tier memory): counting must never
    construct the embedding function, which is what loads the ~300MB+ ONNX model.
    (Checking sys.modules for 'onnxruntime' wouldn't prove anything here: `import
    chromadb` alone already imports it as chromadb's own internal side effect,
    regardless of what count_chunks() does - confirmed directly, not assumed. The
    real guarantee is that the expensive constructor is never called.)"""
    calls = []
    monkeypatch.setattr(ingest, "get_embedding_function", lambda: calls.append(1))
    ingest.count_chunks(str(tmp_path / "never_ingested_2"))
    assert calls == []


class TestGetReadyCollection:
    """get_ready_collection() is the only thing allowed to load the embedding runtime
    (only app/retriever.py, i.e. only the MCP server subprocess, calls it) - see its
    docstring in app/ingest.py for why that matters."""

    def test_builds_an_empty_index_lazily(self, tmp_path, expected_count):
        path = str(tmp_path / "lazy")
        assert ingest.count_chunks(path) == 0
        collection = ingest.get_ready_collection(path)
        assert collection.count() == expected_count == ingest.count_chunks(path)

    def test_does_not_rebuild_an_already_populated_index(self, db, monkeypatch):
        calls = []
        monkeypatch.setattr(ingest, "ingest", lambda *a, **k: calls.append(1))
        ingest.get_ready_collection(db)
        assert calls == []  # `db` fixture already has data; must not re-embed it

    def test_concurrent_first_calls_build_exactly_once(self, tmp_path, expected_count):
        """Two /chat requests can race to the MCP session on a still-empty index at
        once (tests/test_agent.py proves the agent supports concurrent requests over
        one shared session) - the lock must serialize them, not double-build."""
        path = str(tmp_path / "race")
        real_ingest, call_count = ingest.ingest, []
        lock = threading.Lock()

        def counted_ingest(*a, **k):
            with lock:
                call_count.append(1)
            return real_ingest(*a, **k)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ingest, "ingest", counted_ingest)
            threads = [threading.Thread(target=ingest.get_ready_collection, args=(path,)) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(call_count) == 1
        assert ingest.count_chunks(path) == expected_count


def test_smoke_queries_all_hit_their_expected_document(db, capsys):
    assert ingest.smoke(db) is True
    out = capsys.readouterr().out
    assert out.count("PASS") == len(ingest.SMOKE_QUERIES) and "FAIL" not in out


def test_cli_ingests_and_runs_the_smoke_test(tmp_path, monkeypatch, capsys, expected_count):
    monkeypatch.setattr(sys, "argv", ["ingest", "--db", str(tmp_path / "cli"), "--reset", "--smoke"])
    ingest.main()
    assert f"Indexed {expected_count} chunks" in capsys.readouterr().out


def test_cli_exits_nonzero_when_a_smoke_query_misses(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "SMOKE_QUERIES", {"How much PTO do I get per year?": "POL-HR-004"})
    monkeypatch.setattr(sys, "argv", ["ingest", "--db", str(tmp_path / "cli2"), "--smoke"])
    with pytest.raises(SystemExit) as exc:
        ingest.main()
    assert exc.value.code == 1


def test_config_is_imported_before_chromadb_so_telemetry_stays_off():
    """app.config sets ANONYMIZED_TELEMETRY before chromadb reads it at import time; an
    import sorter reordering app/ingest.py would silently break that. sys.modules keeps
    insertion order, so check the order in a fresh interpreter."""
    code = (
        "import os, sys\n"
        "os.environ.pop('ANONYMIZED_TELEMETRY', None)\n"
        "import app.ingest\n"
        "mods = list(sys.modules)\n"
        "assert mods.index('app.config') < mods.index('chromadb'), 'chromadb imported before app.config'\n"
        "assert os.environ['ANONYMIZED_TELEMETRY'] == 'False'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=config.ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]
