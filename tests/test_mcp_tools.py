"""MCP server tests: a real MCP client spawns mcp/server.py over stdio and
discovers/calls its tools — no direct Python calls into the tool functions.

Requires the vector store: `python -m app.ingest --reset`.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp" / "server.py"

EXPECTED_TOOLS = {
    "search_policy_documents",
    "get_policy_section",
    "lookup_employee_profile",
    "check_pto_balance",
    "lookup_benefits_status",
}

CALLS = {
    "search": ("search_policy_documents", {"query": "How many PTO days do I get?", "top_k": 3}),
    "search_off_topic": ("search_policy_documents", {"query": "best pizza topping"}),
    "section": ("get_policy_section", {"doc_id": "POL-HR-001", "section": "PTO Accrual Rates"}),
    "section_case_insensitive": (
        "get_policy_section", {"doc_id": "POL-HR-001", "section": "pto accrual rates"},
    ),
    "section_missing": ("get_policy_section", {"doc_id": "POL-HR-001", "section": "Nope"}),
    "profile": ("lookup_employee_profile", {"employee_id": "E001"}),
    "profile_missing": ("lookup_employee_profile", {"employee_id": "E999"}),
    "pto": ("check_pto_balance", {"employee_id": "E001"}),
    "pto_missing": ("check_pto_balance", {"employee_id": "E999"}),
    "benefits": ("lookup_benefits_status", {"employee_id": "E001"}),
    "benefits_missing": ("lookup_benefits_status", {"employee_id": "E999"}),
}


async def _run_session() -> dict:
    params = StdioServerParameters(
        command=sys.executable, args=[str(SERVER_PATH)], env=dict(os.environ)
    )
    out: dict = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            out["tools"] = (await session.list_tools()).tools
            for key, (name, args) in CALLS.items():
                result = await session.call_tool(name, args)
                # FastMCP emits one content item per list element, so a list-returning
                # tool (search) must be read from all items, not just the first.
                parsed = [json.loads(c.text) for c in result.content]
                out[key] = (result.isError, parsed if name == "search_policy_documents" else parsed[0])
    return out


@pytest.fixture(scope="module")
def mcp_results() -> dict:
    """Spawn the server once, discover tools and make every call in CALLS."""
    return asyncio.run(_run_session())


def test_discovers_all_five_tools(mcp_results):
    assert {t.name for t in mcp_results["tools"]} >= EXPECTED_TOOLS


def test_tools_have_descriptions_and_input_schemas(mcp_results):
    for tool in mcp_results["tools"]:
        assert tool.description
        assert tool.inputSchema["type"] == "object"


def test_no_call_raised_a_protocol_error(mcp_results):
    for key in CALLS:
        is_error, _ = mcp_results[key]
        assert not is_error, f"{key} returned an MCP error"


def test_search_returns_typed_chunks(mcp_results):
    _, chunks = mcp_results["search"]
    assert 0 < len(chunks) <= 3
    assert chunks[0]["doc_id"] == "POL-HR-001"
    assert set(chunks[0]) == {"doc_id", "title", "section", "source_file", "text", "score"}


def test_search_off_topic_is_empty(mcp_results):
    # An empty list serializes to no content items at all.
    _, chunks = mcp_results["search_off_topic"]
    assert not chunks


def test_get_policy_section_returns_full_section(mcp_results):
    _, section = mcp_results["section"]
    assert section["doc_id"] == "POL-HR-001"
    assert section["section"] == "PTO Accrual Rates"
    assert "Years of Service" in section["text"]


def test_get_policy_section_is_case_insensitive(mcp_results):
    assert mcp_results["section_case_insensitive"][1] == mcp_results["section"][1]


def test_get_policy_section_missing_returns_structured_error(mcp_results):
    _, err = mcp_results["section_missing"]
    assert err["error"] == "not_found"


def test_employee_tools_return_records(mcp_results):
    assert mcp_results["profile"][1]["name"] == "Alice Johnson"
    assert mcp_results["pto"][1]["available_hours"] == 96.0
    assert mcp_results["benefits"][1]["medical_plan"] == "Acme Flex"


@pytest.mark.parametrize("key", ["profile_missing", "pto_missing", "benefits_missing"])
def test_unknown_employee_returns_structured_error(mcp_results, key):
    _, err = mcp_results[key]
    assert err == {"error": "employee_not_found", "employee_id": "E999"}
