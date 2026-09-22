"""Day 2 tests: corpus loading produces well-formed, correctly-tagged chunks."""

from app import config
from app.loaders import load_corpus


def test_loads_all_ten_documents():
    chunks = load_corpus(config.CORPUS_DIR)
    doc_ids = {c.doc_id for c in chunks}
    assert len(doc_ids) == 10


def test_covers_all_three_formats():
    chunks = load_corpus(config.CORPUS_DIR)
    formats = {c.fmt for c in chunks}
    assert formats == {"markdown", "html", "pdf"}


def test_chunks_stay_under_max_chars():
    chunks = load_corpus(config.CORPUS_DIR)
    assert all(len(c.text) <= 1200 for c in chunks)


def test_metadata_fields_present():
    chunks = load_corpus(config.CORPUS_DIR)
    for c in chunks[:5]:
        assert c.doc_id and c.title and c.section and c.source_file
        m = c.metadata()
        assert "text" not in m


def test_pto_policy_doc_id_detected():
    chunks = load_corpus(config.CORPUS_DIR)
    pto = [c for c in chunks if c.source_file == "01-pto-policy.md"]
    assert pto
    assert all(c.doc_id == "POL-HR-001" for c in pto)
