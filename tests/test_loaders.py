"""Day 2 tests: corpus loading produces well-formed, correctly-tagged chunks."""

from app import config
from app.loaders import load_corpus


def test_loads_all_documents():
    chunks = load_corpus(config.CORPUS_DIR)
    doc_ids = {c.doc_id for c in chunks}
    assert len(doc_ids) == 17


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


# --- split_text -------------------------------------------------------------

from app.loaders import Chunk, split_text  # noqa: E402


def test_split_text_keeps_short_text_in_one_chunk():
    assert split_text("one paragraph") == ["one paragraph"]


def test_split_text_empty_input_gives_no_chunks():
    assert split_text("  \n\n  ") == []


def test_split_text_packs_paragraphs_up_to_the_limit():
    paragraphs = ["a" * 40] * 6  # 6 x 40 chars, joined by blank lines
    chunks = split_text("\n\n".join(paragraphs), max_chars=100)
    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) == 3  # two 40-char paragraphs fit per chunk
    assert "".join(chunks).replace("\n", "") == "a" * 240  # nothing lost


def test_split_text_breaks_an_oversize_paragraph_on_line_boundaries():
    table = "\n".join(f"| row {i} | value {i} |" for i in range(30))  # one long "paragraph"
    chunks = split_text(table, max_chars=120)
    assert len(chunks) > 1 and all(len(c) <= 120 for c in chunks)
    assert all(line.startswith("| row") for c in chunks for line in c.split("\n"))  # no torn rows


# --- per-format behaviour ---------------------------------------------------


def _chunks_for(source_file: str):
    return [c for c in load_corpus(config.CORPUS_DIR) if c.source_file == source_file]


def test_html_loader_extracts_sections_lists_and_tables():
    chunks = _chunks_for("09-holidays-policy.html")
    assert chunks and {c.doc_id for c in chunks} == {"POL-HR-009"}
    assert {c.fmt for c in chunks} == {"html"}
    assert {c.title for c in chunks} == {"Company Holidays Policy"}
    sections = {c.section for c in chunks}
    assert "Eligibility" in sections
    holiday_text = " ".join(c.text for c in chunks)
    assert "Juneteenth" in holiday_text
    assert "| Holiday |" in holiday_text  # table rendered as pipe rows
    assert "- Full-time employees" in holiday_text  # list rendered as bullets


def test_pdf_loader_detects_headings_by_font_size():
    chunks = _chunks_for("10-leave-of-absence-policy.pdf")
    assert chunks and {c.doc_id for c in chunks} == {"POL-HR-010"}
    assert {c.fmt for c in chunks} == {"pdf"}
    assert {c.title for c in chunks} == {"Leave of Absence Policy"}
    sections = {c.section for c in chunks}
    assert {"Overview", "Family and Medical Leave (FMLA)", "Parental Leave"} <= sections
    assert not any(c.text.startswith(c.section) for c in chunks)  # heading isn't duplicated in the body


def test_document_metadata_preamble_is_not_indexed():
    for c in load_corpus(config.CORPUS_DIR):
        assert "Document ID" not in c.text and "Effective Date" not in c.text, c.chunk_id


def test_section_headings_have_numbering_stripped():
    sections = {c.section for c in load_corpus(config.CORPUS_DIR)}
    assert "PTO Accrual Rates" in sections and "3. PTO Accrual Rates" not in sections


def test_chunk_ids_are_unique():
    ids = [c.chunk_id for c in load_corpus(config.CORPUS_DIR)]
    assert len(ids) == len(set(ids))


def test_embed_text_prefixes_title_and_section():
    c = Chunk("X-000", "X", "Title", "Section", "f.md", "markdown", "body")
    assert c.embed_text == "Title - Section\nbody"
    assert "text" not in c.metadata() and c.metadata()["chunk_id"] == "X-000"
