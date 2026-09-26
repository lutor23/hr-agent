"""Ingest tests: build a throwaway ChromaDB in tmp_path (never touches ./chroma_db)."""

import subprocess
import sys

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


def test_count_chunks_does_not_load_torch_in_the_web_process(tmp_path):
    """The web process must stay light (free-tier memory): counting must never pull in
    torch/sentence-transformers. Checked in a fresh interpreter, since this one has them."""
    code = (
        "import sys\n"
        "from app.ingest import count_chunks\n"
        f"count_chunks({str(tmp_path / 'x')!r})\n"
        "loaded = [m for m in ('torch', 'sentence_transformers') if m in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=config.ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]


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
