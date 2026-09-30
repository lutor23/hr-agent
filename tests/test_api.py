"""API tests: the real FastAPI app (real lifespan, real MCP server subprocess) driven
through Starlette's TestClient, with a scripted fake LLM.

Requires the vector store: `python -m app.ingest --reset`.
"""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError

from app import main
from app.main import create_app
from tests.test_agent import calls, final, scripted, tool_call


@pytest.fixture(autouse=True)
def offline_llm_for_mcp_server(monkeypatch):
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://127.0.0.1:9/v1")


def client(llm_fn=None):
    return TestClient(create_app(llm_fn=llm_fn or scripted(final("ok"))))


def test_app_starts_and_health_reports_ok():
    with client() as c:
        r = c.get("/health")
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "ok"
    assert body["chroma_docs"] > 0
    assert body["mcp_connected"] is True and body["mcp_tools"] == 7
    assert body["version"] == main.VERSION


def test_chat_round_trip_returns_answer_citations_and_trace():
    llm_fn = scripted(
        calls(tool_call("check_pto_balance", employee_id="E001")),
        calls(tool_call("get_policy_section", doc_id="POL-HR-001", section="PTO Request Process")),
        final("You have 96h. Extended leave needs department head approval [POL-HR-001: PTO Request Process]."),
    )
    with client(llm_fn) as c:
        r = c.post("/chat", json={"message": "Can I take two weeks off?", "employee_id": "E001", "session_id": "s1"})
    body = r.json()
    assert r.status_code == 200
    assert "department head" in body["answer"]
    assert [s["tool"] for s in body["trace"]] == ["check_pto_balance", "get_policy_section"]
    assert body["tools_used"] == ["check_pto_balance", "get_policy_section"]
    assert body["citations"][0]["doc_id"] == "POL-HR-001" and body["citations"][0]["snippet"]
    assert body["latency_ms"] > 0 and body["error"] is None and body["escalated"] is False


def test_chat_rejects_empty_and_oversized_messages():
    with client() as c:
        assert c.post("/chat", json={"message": ""}).status_code == 422
        assert c.post("/chat", json={}).status_code == 422
        assert c.post("/chat", json={"message": "x" * 2001}).status_code == 422


def test_llm_failure_is_a_200_with_an_error_flag():
    timeout = APITimeoutError(request=httpx.Request("POST", "http://x"))
    with client(scripted(timeout)) as c:
        r = c.post("/chat", json={"message": "hi"})
    assert r.status_code == 200 and r.json()["error"] == "APITimeoutError"


def test_employee_can_only_access_own_records_via_api():
    llm_fn = scripted(calls(tool_call("check_pto_balance", employee_id="E002")), final("Not allowed."))
    with client(llm_fn) as c:
        body = c.post("/chat", json={"message": "PTO of E002?", "employee_id": "E001"}).json()
    assert body["trace"][0]["ok"] is False and body["trace"][0]["result_summary"] == "error: not_authorized"


def test_health_reports_degraded_for_an_empty_index(monkeypatch):
    monkeypatch.setattr(main, "count_chunks", lambda *a, **k: 0)
    with client() as c:
        health = c.get("/health")
    assert health.status_code == 503
    assert health.json()["status"] == "degraded" and health.json()["chroma_docs"] == 0


def test_chat_does_not_require_the_index_to_be_prebuilt(monkeypatch):
    """/chat no longer gates on count_chunks(): an empty index is the MCP server
    subprocess's problem to self-heal (app/ingest.get_ready_collection, tested in
    test_ingest.py), not a reason for the FastAPI process to refuse the request."""
    monkeypatch.setattr(main, "count_chunks", lambda *a, **k: 0)
    with client() as c:
        r = c.post("/chat", json={"message": "hi"})
    assert r.status_code == 200


def test_mcp_server_down_gives_503_and_degraded_health(monkeypatch):
    async def broken_connect(self):
        raise RuntimeError("cannot spawn MCP server")

    monkeypatch.setattr(main.HRAgent, "connect", broken_connect)
    with client() as c:  # the app still starts
        health = c.get("/health")
        chat = c.post("/chat", json={"message": "hi"})
    assert health.status_code == 503 and health.json()["mcp_connected"] is False
    assert chat.status_code == 503 and "MCP" in chat.json()["detail"]


def test_slow_request_times_out_with_504(monkeypatch):
    async def slow_llm(messages, tools):
        await asyncio.sleep(5)

    monkeypatch.setattr(main, "CHAT_TIMEOUT_S", 0.3)
    with client(slow_llm) as c:
        r = c.post("/chat", json={"message": "hi"})
    assert r.status_code == 504


def test_ui_page_is_served():
    with client() as c:
        r = c.get("/")
    assert r.status_code == 200 and "Acme HR Assistant" in r.text


def test_employees_endpoint_exposes_only_id_and_name():
    with client() as c:
        rows = c.get("/employees").json()
    assert len(rows) == 10 and all(set(r) == {"employee_id", "name"} for r in rows)
