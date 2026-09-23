"""Manual Day 4 verification: a real MCP client talking to mcp/server.py over
stdio (spawned as a subprocess), not a direct Python function call.

Run: python mcp/_smoke_test.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = Path(__file__).resolve().parent / "server.py"

CALLS = [
    ("search_policy_documents", {"query": "How many PTO days do I get?", "top_k": 3}),
    ("get_policy_section", {"doc_id": "POL-HR-001", "section": "PTO Accrual Rates"}),
    ("get_policy_section", {"doc_id": "POL-HR-001", "section": "Does Not Exist"}),
    ("lookup_employee_profile", {"employee_id": "E001"}),
    ("lookup_employee_profile", {"employee_id": "E999"}),
    ("check_pto_balance", {"employee_id": "E001"}),
    ("lookup_benefits_status", {"employee_id": "E001"}),
]


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=[str(SERVER_PATH)], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = (await session.list_tools()).tools
            print(f"Registered tools ({len(tools)}):")
            for t in tools:
                print(f"  - {t.name}: {t.description.splitlines()[0]}")
            assert len(tools) >= 5, f"expected >=5 tools, got {len(tools)}"

            print("\nTool calls:")
            for name, args in CALLS:
                result = await session.call_tool(name, args)
                text = result.content[0].text if result.content else "<empty>"
                try:
                    text = json.dumps(json.loads(text), indent=2)[:300]
                except (json.JSONDecodeError, TypeError):
                    pass
                status = "ERROR" if result.isError else "ok"
                print(f"\n  {name}({args}) -> [{status}]\n  {text}")

    print("\nAll tools reachable through a real MCP client/server round-trip.")


if __name__ == "__main__":
    asyncio.run(main())
