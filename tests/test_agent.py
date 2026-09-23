"""Agent orchestrator tests.

The LLM is a scripted fake so results are deterministic and offline, but everything
else is real: the agent spawns mcp/server.py and every tool call goes through the MCP
client session. Requires the vector store: `python -m app.ingest --reset`.
"""

import asyncio
import itertools
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from app.agent import HRAgent


def tool_call(name: str, **args):
    return SimpleNamespace(
        id=f"call-{next(_ids)}", function=SimpleNamespace(name=name, arguments=json.dumps(args))
    )


_ids = itertools.count(1)


def calls(*tool_calls):
    return SimpleNamespace(content="", tool_calls=list(tool_calls))


def final(text: str):
    return SimpleNamespace(content=text, tool_calls=None)


def scripted(*replies):
    """Fake LLM that returns the given replies in order and records the messages it saw."""
    queue = list(replies)
    seen: list[list[dict]] = []

    async def llm_fn(messages, tools):
        seen.append([dict(m) for m in messages])
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    llm_fn.seen = seen
    return llm_fn


def run_agent(llm_fn, message="hi", employee_id=None, **kw):
    async def go():
        async with HRAgent(llm_fn=llm_fn, **kw) as agent:
            return await agent.run(message, employee_id=employee_id)

    return asyncio.run(go())


@pytest.fixture(autouse=True)
def offline_llm_for_mcp_server(monkeypatch):
    # draft_hr_email calls the LLM from inside the server subprocess; point it at a
    # dead port so it deterministically takes its template fallback.
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://127.0.0.1:9/v1")


def test_agent_discovers_all_seven_tools_over_mcp():
    async def go():
        async with HRAgent(llm_fn=scripted()) as agent:
            return agent.tool_names

    assert set(asyncio.run(go())) == {
        "search_policy_documents", "get_policy_section", "lookup_employee_profile",
        "check_pto_balance", "lookup_benefits_status", "create_mock_hr_ticket", "draft_hr_email",
    }


def test_multi_step_workflow_pto_balance_then_policy():
    llm_fn = scripted(
        calls(tool_call("check_pto_balance", employee_id="E001")),
        calls(tool_call("get_policy_section", doc_id="POL-HR-001", section="PTO Request Process")),
        final("You have 96h. Extended leave needs department head approval "
              "[POL-HR-001: PTO Request Process]."),
    )
    r = run_agent(llm_fn, "Can I take two weeks off?", employee_id="E001")

    assert [s.tool for s in r.trace] == ["check_pto_balance", "get_policy_section"]
    assert all(s.ok for s in r.trace)
    assert r.tools_used == ["check_pto_balance", "get_policy_section"]
    assert [(c.doc_id, c.section) for c in r.citations] == [("POL-HR-001", "PTO Request Process")]
    assert r.citations[0].snippet
    assert r.error is None and not r.escalated
    # The real tool result (E001's 96h balance) was fed back to the model.
    tool_msg = next(m for m in llm_fn.seen[1] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["available_hours"] == 96.0


def test_search_results_are_read_as_a_list_and_citable():
    llm_fn = scripted(
        calls(tool_call("search_policy_documents", query="how many PTO days do I get", top_k=3)),
        final("See [POL-HR-001: PTO Accrual Rates]."),
    )
    r = run_agent(llm_fn)
    assert r.trace[0].result_summary.endswith("result(s)")
    assert r.citations and r.citations[0].doc_id == "POL-HR-001"


def test_citation_with_extra_detail_still_matches_returned_section():
    llm_fn = scripted(
        calls(tool_call("get_policy_section", doc_id="POL-HR-001", section="PTO Request Process")),
        final("Approval needed [POL-HR-001: PTO Request Process, section 4.3]."),
    )
    assert len(run_agent(llm_fn).citations) == 1


def test_citation_no_tool_returned_is_dropped():
    llm_fn = scripted(
        calls(tool_call("get_policy_section", doc_id="POL-HR-001", section="PTO Request Process")),
        final("Also [POL-HR-004: Medical Plans] and [POL-HR-999: Made Up]."),
    )
    assert run_agent(llm_fn).citations == []


def test_employee_cannot_read_another_employees_records():
    llm_fn = scripted(
        calls(tool_call("check_pto_balance", employee_id="E002")),
        final("Sorry, I can only share your own records."),
    )
    r = run_agent(llm_fn, employee_id="E001")
    assert r.trace[0].ok is False
    assert r.trace[0].result_summary == "error: not_authorized"
    tool_msg = next(m for m in llm_fn.seen[1] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["error"] == "not_authorized"
    assert "available_hours" not in tool_msg["content"]  # E002's balance never left the server


def test_unknown_employee_is_a_failed_step_not_a_crash():
    llm_fn = scripted(calls(tool_call("check_pto_balance", employee_id="E999")), final("No such employee."))
    r = run_agent(llm_fn)
    assert r.trace[0].ok is False and r.trace[0].result_summary == "error: employee_not_found"
    assert r.answer == "No such employee." and r.error is None


def test_ticket_escalation_is_flagged_and_mock():
    llm_fn = scripted(
        calls(tool_call("create_mock_hr_ticket", employee_id="E001", type="leave", description="FMLA question")),
        final("I opened a mock ticket."),
    )
    r = run_agent(llm_fn, employee_id="E001")
    assert r.escalated is True
    result = json.loads(next(m for m in llm_fn.seen[1] if m["role"] == "tool")["content"])
    assert result["ticket_id"] == "HR-0001" and result["mock"] is True and "mock" in result["status"]


def test_invalid_ticket_type_does_not_count_as_escalation():
    llm_fn = scripted(
        calls(tool_call("create_mock_hr_ticket", employee_id="E001", type="lawsuit", description="x")),
        final("Couldn't file that."),
    )
    r = run_agent(llm_fn)
    assert r.escalated is False and r.trace[0].ok is False


def test_email_is_draft_only_and_falls_back_when_llm_unavailable():
    llm_fn = scripted(
        calls(tool_call("draft_hr_email", to="hr@acmecorp.example.com", subject="PTO", context="I want 2 weeks off in December.")),
        final("Here's a draft."),
    )
    r = run_agent(llm_fn)
    draft = json.loads(next(m for m in llm_fn.seen[1] if m["role"] == "tool")["content"])
    assert draft["sent"] is False and draft["llm_generated"] is False
    assert "2 weeks off in December" in draft["body"]
    assert r.trace[0].ok


def test_tool_unavailable_is_reported_and_agent_still_answers():
    async def go():
        agent = HRAgent(llm_fn=scripted(
            calls(tool_call("check_pto_balance", employee_id="E001")),
            final("I can't reach the HR systems right now."),
        ))
        await agent.connect()
        await agent.close()  # server is gone: simulates the MCP tool being down
        return await agent.run("PTO?", employee_id="E001")

    r = asyncio.run(go())
    assert r.trace[0].ok is False and r.trace[0].result_summary == "error: tool_unavailable"
    assert "can't reach" in r.answer


def test_missing_employee_id_is_stated_in_the_system_prompt():
    llm_fn = scripted(final("What's your employee ID?"))
    run_agent(llm_fn, "How much PTO do I have?")
    assert "No employee ID is available" in llm_fn.seen[0][0]["content"]


def test_llm_timeout_returns_graceful_error():
    timeout = APITimeoutError(request=httpx.Request("POST", "http://x"))
    r = run_agent(scripted(timeout))
    assert r.error == "APITimeoutError" and "try again" in r.answer


def test_runaway_tool_loop_is_stopped():
    forever = [calls(tool_call("lookup_employee_profile", employee_id="E001")) for _ in range(10)]
    r = run_agent(scripted(*forever), max_steps=3)
    assert r.error == "max_steps_exceeded" and len(r.trace) == 3
