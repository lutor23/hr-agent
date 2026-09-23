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
this module by dotted path (`mcp.server`) from elsewhere in the repo; spawn it
as a subprocess over stdio instead, as app/agent.py and the tests do.
"""

import sys
from pathlib import Path

# Running as a script (see module docstring), so the repo root isn't on
# sys.path automatically — add it to import the app package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402  (must follow sys.path fix)

from app import config, employee_data, llm  # noqa: E402
from app.retriever import get_section, retrieve  # noqa: E402

mcp = FastMCP("hr-policy-assistant")

TICKET_TYPES = ("pto", "benefits", "payroll", "leave", "equipment", "conduct", "other")
# Mock ticket store: lives only as long as this server process. Nothing here is a
# real HR system, and nothing is ever sent anywhere.
_TICKETS: dict[str, dict] = {}


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


@mcp.tool()
def create_mock_hr_ticket(employee_id: str, type: str, description: str) -> dict:
    """Open a MOCK HR case for an employee (in-memory only; no real HR system is
    touched). Use to escalate something policy documents can't resolve. `type`
    is one of: pto, benefits, payroll, leave, equipment, conduct, other.

    Returns the ticket (ticket_id, status, ...) or a structured error for an
    unknown employee, invalid type, or empty description.
    """
    if employee_data.get_employee(employee_id) is None:
        return {"error": "employee_not_found", "employee_id": employee_id}
    ticket_type = type.strip().lower()
    if ticket_type not in TICKET_TYPES:
        return {"error": "invalid_ticket_type", "type": type, "valid_types": list(TICKET_TYPES)}
    if not description.strip():
        return {"error": "empty_description"}
    ticket_id = f"HR-{len(_TICKETS) + 1:04d}"
    _TICKETS[ticket_id] = {
        "ticket_id": ticket_id,
        "employee_id": employee_id,
        "type": ticket_type,
        "description": description.strip(),
        "status": "open (mock)",
        "mock": True,
    }
    return _TICKETS[ticket_id]


@mcp.tool()
def draft_hr_email(to: str, subject: str, context: str) -> dict:
    """Draft (never send) a short professional email about an HR matter, written
    only from the facts in `context`. The result is a draft for the user to
    review; `sent` is always false.
    """
    body = None
    try:
        completion = llm.get_client().chat.completions.create(
            model=config.LLM_MODEL,
            temperature=0.3,
            messages=[
                {
                    "role": "system",
                    "content": "Write a concise, professional workplace email body (no subject "
                    "line) written BY the employee TO the recipient, addressing the "
                    "recipient (not the employee). Use ONLY facts from the provided "
                    "context; do not invent dates, numbers or commitments. Sign off with "
                    "'[Your name]'.",
                },
                {"role": "user", "content": f"To: {to}\nSubject: {subject}\nContext: {context}"},
            ],
        )
        body = (completion.choices[0].message.content or "").strip() or None
    except Exception:  # LLM unavailable: fall back to a plain template below
        body = None
    generated = body is not None
    if body is None:
        body = f"Hello,\n\n{context.strip()}\n\nThank you,\n[Your name]"
    return {"to": to, "subject": subject, "body": body, "sent": False, "llm_generated": generated}


if __name__ == "__main__":
    mcp.run(transport="stdio")
