"""Day 3 smoke tests for retrieval, prompt building and citation extraction.

Requires the vector store to already be built: `python -m app.ingest --reset`.
"""

import pytest

from app.retriever import (
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


# --- get_section / retrieve options ----------------------------------------

from types import SimpleNamespace  # noqa: E402

import httpx  # noqa: E402
from openai import APITimeoutError  # noqa: E402

from app import retriever  # noqa: E402
from app.retriever import get_section  # noqa: E402


class TestGetSection:
    def test_exact_lookup_returns_full_text_and_metadata(self):
        s = get_section("POL-HR-001", "PTO Accrual Rates")
        assert s["doc_id"] == "POL-HR-001" and s["source_file"] == "01-pto-policy.md"
        assert "Years of Service" in s["text"]

    def test_lookup_is_case_insensitive(self):
        assert get_section("POL-HR-001", "pto accrual RATES") == get_section("POL-HR-001", "PTO Accrual Rates")

    def test_unknown_section_or_doc_returns_none(self):
        assert get_section("POL-HR-001", "No Such Section") is None
        assert get_section("POL-HR-999", "PTO Accrual Rates") is None

    def test_section_from_another_doc_is_not_returned(self):
        assert get_section("POL-HR-002", "PTO Accrual Rates") is None


def test_retrieve_min_score_zero_disables_the_relevance_filter():
    assert retrieve("best pizza topping") == []
    assert len(retrieve("best pizza topping", top_k=3, min_score=0.0)) == 3


def test_retrieve_scores_are_sorted_best_first_and_above_threshold():
    scores = [c.score for c in retrieve("How do I request time off?", top_k=5)]
    assert scores == sorted(scores, reverse=True)
    assert all(s >= retriever.MIN_SCORE for s in scores)


# --- ask(): the single-shot RAG path (LLM faked) ----------------------------


class FakeLLM:
    """Stands in for the OpenAI client returned by llm.get_client()."""

    def __init__(self, content="You get 10 days [1].", error=None):
        self.content, self.error, self.requests = content, error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(retriever.llm, "get_client", lambda: fake)
    return fake


def test_ask_answers_with_citations_from_the_cited_excerpts(fake_llm):
    r = retriever.ask("How many PTO days do I get per year?")
    assert r.answer == "You get 10 days [1]." and r.error is None
    assert len(r.citations) == 1 and r.citations[0].doc_id == "POL-HR-001"
    assert r.tools_used == ["search_policy_documents"] and r.latency_ms > 0
    user_prompt = fake_llm.requests[0]["messages"][1]["content"]
    assert "Policy excerpts:" in user_prompt and "Question: How many PTO days" in user_prompt
    assert fake_llm.requests[0]["temperature"] == 0


def test_ask_includes_the_employees_details_in_the_prompt(fake_llm):
    retriever.ask("How much PTO do I have?", employee_id="E001")
    assert "Alice Johnson" in fake_llm.requests[0]["messages"][1]["content"]


def test_ask_off_topic_never_calls_the_llm(fake_llm):
    r = retriever.ask("What's the best pizza topping?")
    assert r.answer == retriever.NO_ANSWER and r.citations == [] and fake_llm.requests == []


def test_ask_unknown_employee_never_calls_the_llm(fake_llm):
    r = retriever.ask("How much PTO do I have?", employee_id="E999")
    assert r.error == "unknown_employee" and "E999" in r.answer and fake_llm.requests == []


def test_ask_llm_failure_falls_back_to_the_top_retrieved_chunk(monkeypatch):
    fake = FakeLLM(error=APITimeoutError(request=httpx.Request("POST", "http://x")))
    monkeypatch.setattr(retriever.llm, "get_client", lambda: fake)
    r = retriever.ask("How many PTO days do I get per year?")
    assert r.error == "APITimeoutError" and "couldn't generate a full answer" in r.answer
    assert len(r.citations) == 1 and r.citations[0].doc_id == "POL-HR-001"


def test_ask_handles_an_empty_llm_reply(monkeypatch):
    monkeypatch.setattr(retriever.llm, "get_client", lambda: FakeLLM(content=None))
    assert retriever.ask("How many PTO days do I get per year?").answer == ""
