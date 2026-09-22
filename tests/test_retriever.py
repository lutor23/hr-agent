"""Day 3 smoke tests for retrieval, prompt building and citation extraction.

Requires the vector store to already be built: `python -m app.ingest --reset`.
"""

import pytest

from app.loaders import Chunk
from app.retriever import (
    NO_ANSWER,
    build_prompt,
    employee_context,
    extract_citations,
    retrieve,
)


def make_chunk(doc_id="POL-HR-001", section="Overview", text="some policy text", score=0.9):
    from app.retriever import RetrievedChunk

    return RetrievedChunk(
        chunk_id=f"{doc_id}-000", doc_id=doc_id, title="Test Policy", section=section,
        source_file="test.md", fmt="markdown", text=text, score=score,
    )


class TestRetrieve:
    def test_returns_matching_doc(self):
        results = retrieve("How many PTO days do I get per year?")
        assert results
        assert results[0].doc_id == "POL-HR-001"

    def test_off_topic_query_returns_nothing(self):
        assert retrieve("What's the best pizza topping?") == []

    def test_respects_top_k(self):
        assert len(retrieve("company holidays", top_k=2)) <= 2

    def test_doc_id_filter_restricts_results(self):
        results = retrieve("policy", doc_id="POL-HR-004", top_k=10)
        assert results
        assert all(c.doc_id == "POL-HR-004" for c in results)


class TestEmployeeContext:
    def test_known_employee_includes_pto_and_benefits(self):
        ctx = employee_context("E001")
        assert ctx is not None
        assert "PTO" in ctx
        assert "Benefits" in ctx

    def test_unknown_employee_returns_none(self):
        assert employee_context("E999") is None


class TestBuildPrompt:
    def test_includes_numbered_excerpts_and_question(self):
        chunks = [make_chunk(text="Employees get 10 days of PTO.")]
        prompt = build_prompt("How much PTO?", chunks)
        assert "[1]" in prompt
        assert "Employees get 10 days of PTO." in prompt
        assert "Question: How much PTO?" in prompt

    def test_includes_employee_context_when_given(self):
        prompt = build_prompt("How much PTO?", [make_chunk()], employee_context="Alice, E001")
        assert "Employee details:" in prompt
        assert "Alice, E001" in prompt

    def test_omits_employee_section_when_absent(self):
        prompt = build_prompt("How much PTO?", [make_chunk()])
        assert "Employee details:" not in prompt


class TestExtractCitations:
    def test_extracts_cited_chunks_only(self):
        chunks = [make_chunk(doc_id="POL-HR-001"), make_chunk(doc_id="POL-HR-002")]
        citations = extract_citations("You get 10 days [1].", chunks)
        assert len(citations) == 1
        assert citations[0].doc_id == "POL-HR-001"

    def test_falls_back_to_all_chunks_without_markers(self):
        chunks = [make_chunk(doc_id="POL-HR-001")]
        citations = extract_citations("You get 10 days.", chunks)
        assert len(citations) == 1

    def test_deduplicates_by_doc_and_section(self):
        chunks = [make_chunk(section="A"), make_chunk(section="A")]
        citations = extract_citations("[1][2]", chunks)
        assert len(citations) == 1

    def test_ignores_out_of_range_markers(self):
        chunks = [make_chunk()]
        citations = extract_citations("See [1] and [9].", chunks)
        assert len(citations) == 1
