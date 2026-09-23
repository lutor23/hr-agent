"""MCP tool server exposing the HR policy RAG index and mock employee data.

Runs over stdio, spawned as a subprocess by whatever MCP client connects to it
(the agent orchestrator in app/agent.py, or the manual smoke test in
mcp/_smoke_test.py). Start it directly:

    python mcp/server.py

Note on the package name: this directory is named `mcp/` per the grader's
required repo layout, which collides with the installed `mcp` SDK package of
the same name. Running this file as a script (not `python -m mcp.server`)
keeps the collision harmless — the script's own directory becomes sys.path[0],
which contains no nested `mcp/` folder, so `import mcp` below still resolves
to the real SDK in site-packages. Do not add an `__init__.py` here or import
this module by dotted path (`mcp.server`) from elsewhere in the repo; use
mcp/_smoke_test.py's approach (importlib by file path) or a subprocess instead.
"""

import sys
from pathlib import Path

# Running as a script (see module docstring), so the repo root isn't on
# sys.path automatically — add it to import the app package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402  (must follow sys.path fix)

from app import employee_data  # noqa: E402
from app.retriever import get_section, retrieve  # noqa: E402

mcp = FastMCP("hr-policy-assistant")


@mcp.tool()
def search_policy_documents(query: str, top_k: int = 5) -> list[dict]:
    """Semantic search over the Acme Corp HR policy corpus.

    Returns the top-k matching chunks (doc_id, title, section, source_file,
    text, cosine similarity score), best first. Chunks below the relevance
    threshold are dropped, so an out-of-corpus query returns an empty list.
    """
    return [
        {
            "doc_id": c.doc_id,
            "title": c.title,
            "section": c.section,
            "source_file": c.source_file,
            "text": c.text,
            "score": c.score,
        }
        for c in retrieve(query, top_k=top_k)
    ]


@mcp.tool()
def get_policy_section(doc_id: str, section: str) -> dict:
    """Full text of one section of one policy document (e.g. doc_id="POL-HR-001",
    section="PTO Accrual Rates"). Use this after search_policy_documents has
    identified the doc_id/section you need, to get its complete text.

    Returns {"error": "not_found", ...} if no chunk matches that doc_id/section.
    """
    result = get_section(doc_id, section)
    if result is None:
        return {"error": "not_found", "doc_id": doc_id, "section": section}
    return result


@mcp.tool()
def lookup_employee_profile(employee_id: str) -> dict:
    """Look up an employee's profile: name, title, department, manager, hire
    date, location, employment type, work arrangement.

    Returns {"error": "employee_not_found", ...} for an unknown employee_id.
    """
    emp = employee_data.get_employee(employee_id)
    if emp is None:
        return {"error": "employee_not_found", "employee_id": employee_id}
    return emp


@mcp.tool()
def check_pto_balance(employee_id: str) -> dict:
    """Look up an employee's current PTO balance: available/pending/used hours,
    annual allotment, and carryover.

    Returns {"error": "employee_not_found", ...} for an unknown employee_id.
    """
    if employee_data.get_employee(employee_id) is None:
        return {"error": "employee_not_found", "employee_id": employee_id}
    balance = employee_data.get_pto_balance(employee_id)
    if balance is None:
        return {"error": "no_pto_record", "employee_id": employee_id}
    return {"employee_id": employee_id, **balance}


@mcp.tool()
def lookup_benefits_status(employee_id: str) -> dict:
    """Look up an employee's benefits enrollment: medical plan, coverage tier,
    dental, vision, HSA, 401(k) contribution rate, enrollment status.

    Returns {"error": "employee_not_found", ...} for an unknown employee_id.
    """
    if employee_data.get_employee(employee_id) is None:
        return {"error": "employee_not_found", "employee_id": employee_id}
    benefits = employee_data.get_benefits(employee_id)
    if benefits is None:
        return {"error": "no_benefits_record", "employee_id": employee_id}
    return {"employee_id": employee_id, **benefits}


if __name__ == "__main__":
    mcp.run(transport="stdio")
