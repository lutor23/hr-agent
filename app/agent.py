"""Agent orchestrator: an LLM tool-calling loop whose tools all live behind the MCP server.

The agent never imports the tool implementations directly. It discovers tools over
MCP (`list_tools`) and executes every call through `session.call_tool`. Each call is
recorded as a TraceStep (tool, args, outcome, timing) — an operational trace, not the
model's reasoning.

Two ways it connects, chosen by config.MCP_TRANSPORT:
  - "stdio" (default): spawns mcp/server.py as a real separate OS process and talks
    to it over the actual MCP wire protocol. What every test uses; what "the MCP
    server" normally means here.
  - "inmemory": runs the same tools in this process instead, over the SDK's in-memory
    ClientSession transport (still genuine MCP protocol objects, just no second
    process). Used only by the deployed Render instance — a stdio subprocess doubles
    the embedding model's memory cost (two processes each loading it), which is what
    OOM-killed real deploys; see _load_mcp_server_module()'s docstring and CLAUDE.md's
    Day 8 entry.

    async with HRAgent() as agent:
        response = await agent.run("How much PTO do I have?", employee_id="E001")

CLI: python -m app.agent "Can I take two weeks off?" --employee E001
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import re
import sys
import time
from contextlib import AsyncExitStack
from types import ModuleType
from typing import Any, Awaitable, Callable, Optional

from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from openai import APIError, APITimeoutError

from app import config, llm
from app.models import ChatResponse, Citation, TraceStep
from mcp import ClientSession, StdioServerParameters

log = logging.getLogger("hr_agent.trace")

SERVER_PATH = config.ROOT / "mcp" / "server.py"


def _load_mcp_server_module() -> ModuleType:
    """Load mcp/server.py as an in-process module (its FastMCP instance, tools and
    background-index-build helper), for MCP_TRANSPORT="inmemory".

    Loaded by file path under an internal name, never as `import mcp.server` — mcp/
    has no `__init__.py` precisely so it never shadows the installed `mcp` SDK
    package of the same name (see mcp/server.py's own module docstring); a dotted
    import here would defeat that. This also means mcp/server.py's own
    `sys.path.insert(...)` line is redundant in this path (the repo root is already
    on sys.path, since this is called from within the `app` package) but harmless.
    """
    spec = importlib.util.spec_from_file_location("_hr_agent_mcp_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
MAX_STEPS = 6
# FastMCP emits one content item per list element, so these tools' results must be
# read from every content item rather than just the first.
LIST_TOOLS = {"search_policy_documents"}
TOOL_RESULT_CHAR_LIMIT = 6000
SNIPPET_CHARS = 240
ESCALATION_TOOL = "create_mock_hr_ticket"

SYSTEM_PROMPT = """You are the Acme Corp HR Assistant. You answer HR questions using tools; \
you have no HR knowledge of your own.

Rules:
1. Policy questions: call search_policy_documents (use get_policy_section for a full \
section). Answer ONLY from what the tools return. If nothing relevant comes back, say you \
couldn't find a policy covering it and suggest contacting HR. Never guess.
2. Personal questions (PTO balance, benefits, profile): use the employee tools with the \
current employee ID. If no employee ID is available, ask the user for it instead of guessing.
3. Combine tools when needed (e.g. PTO balance + the PTO or leave policy for "can I take \
two weeks off?"). Keep policy facts separate from your recommendations.
4. Cite every policy claim inline as [DOC_ID: Section], e.g. [POL-HR-001: PTO Accrual \
Rates], using the exact doc_id and section name a tool returned (nothing extra inside the \
brackets). Employee data (balances, profiles, benefits) comes from employee tools and is \
NOT a policy citation.
5. create_mock_hr_ticket and draft_hr_email are MOCK actions: nothing is really filed or \
sent. Only use them when the user asks, or when policy says HR must handle it, and tell \
the user plainly that the ticket/email is a mock or a draft.
6. If the request is ambiguous, ask ONE short clarifying question instead of guessing.
7. Be concise and specific: include numbers, deadlines and steps from the policy.

{employee_line}"""

def _snippet(text: str) -> str:
    """Plain-text excerpt: markdown heading marks and line breaks flattened."""
    return re.sub(r"\s+", " ", re.sub(r"#+\s*", "", text)).strip()[:SNIPPET_CHARS]


CITATION_RE = re.compile(r"\[(POL-[A-Z]+-\d+)(?:\s*:\s*([^\]]+))?\]")

# Some free-tier models substitute other delimiters/characters for the plain ASCII
# "[DOC-ID: Section]" the system prompt asks for. Observed for real across two Day 9
# evaluation runs: nvidia/nemotron-3-super-120b-a12b used U+2011 NON-BREAKING HYPHEN
# inside doc IDs ("POL‑IT‑001"), fullwidth CJK brackets ("【POL-HR-005: ...】"), and
# plain parentheses ("(POL-IT-001: ...)") instead of square brackets — all three
# silently defeated CITATION_RE and dropped citations from fully correct, well-cited
# answers. Normalizing known lookalikes before matching (not applied to the answer
# text actually shown to the user — translate() here only feeds the regex) is far
# more robust than trying to enumerate every variant inside the regex itself, and
# this affects real /chat responses, not just eval scoring. Folding "(" ")" into
# "[" "]" globally before matching is safe even with unrelated parenthetical text
# elsewhere in the answer: CITATION_RE still requires the literal "POL-XX-NNN"
# pattern inside, so prose like "(see the handbook)" never matches regardless.
_CITATION_MARKUP_NORMALIZE = str.maketrans(
    {
        "【": "[", "［": "[", "(": "[",  # 【 ［ ( -> [
        "】": "]", "］": "]", ")": "]",  # 】 ］ ) -> ]
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",  # dash variants -> -
    }
)

# An LLM turn: takes chat messages + OpenAI-format tool schemas, returns an object with
# `.content` and `.tool_calls` (each with `.id`, `.function.name`, `.function.arguments`).
LLMFn = Callable[[list[dict], list[dict]], Awaitable[Any]]


class LLMResponseError(RuntimeError):
    """Raised when the LLM API returns HTTP 200 but a response with no usable choice.

    Observed for real on OpenRouter's free tier: an upstream provider hiccup can come
    back as 200 OK with `choices: null` in the body instead of a 4xx/5xx the openai
    client would raise as APIError. Caught the same way as APITimeoutError/APIError
    in HRAgent.run() below - without this, it crashed a live request with an
    unhandled TypeError ('NoneType' object is not subscriptable) instead of the
    graceful "couldn't reach the language model" answer other LLM failures already get.
    """


async def default_llm(messages: list[dict], tools: list[dict]) -> Any:
    completion = await llm.get_async_client().chat.completions.create(
        model=config.LLM_MODEL, messages=messages, tools=tools, temperature=0
    )
    if not completion.choices:
        raise LLMResponseError(f"OpenRouter returned no choices: {completion!r}")
    return completion.choices[0].message


def _summarize(result: Any) -> str:
    if isinstance(result, list):
        return f"{len(result)} result(s)"
    if isinstance(result, dict) and "error" in result:
        return f"error: {result['error']}"
    if isinstance(result, dict):
        return "ok: " + ", ".join(list(result)[:6])
    return str(result)[:80]


class HRAgent:
    """Holds one MCP session (a server subprocess, or an in-process one - see
    config.MCP_TRANSPORT) and runs many questions over it."""

    def __init__(
        self, llm_fn: Optional[LLMFn] = None, max_steps: int = MAX_STEPS, transport: Optional[str] = None
    ):
        self._llm = llm_fn or default_llm
        self._max_steps = max_steps
        self._transport = transport or config.MCP_TRANSPORT
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._tools: list[dict] = []
        self._index_task: Optional[asyncio.Task] = None

    async def __aenter__(self) -> "HRAgent":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self) -> None:
        self._stack = AsyncExitStack()
        if self._transport == "inmemory":
            server_module = _load_mcp_server_module()
            self._session = await self._stack.enter_async_context(
                create_connected_server_and_client_session(server_module.mcp._mcp_server)
            )
            # Same reasoning as mcp/server.py's own _serve(): build in a background
            # thread, concurrently with serving requests, so /health goes "ok" without
            # needing traffic and without blocking this coroutine (and therefore
            # FastAPI's own startup) on the embed. Kept on self so it isn't
            # garbage-collected mid-flight; close() cancels it if still running.
            self._index_task = asyncio.create_task(server_module._build_index_in_background())
        else:
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(SERVER_PATH)],
                env={**os.environ, "FASTMCP_LOG_LEVEL": "WARNING"},
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        listed = (await self._session.list_tools()).tools
        self._tools = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema},
            }
            for t in listed
        ]

    async def close(self) -> None:
        if self._index_task is not None:
            self._index_task.cancel()
            self._index_task = None
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = self._session = None

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def ping(self, timeout: float = 5.0) -> bool:
        """True if the MCP server subprocess answers a protocol-level ping."""
        if self._session is None:
            return False
        try:
            await asyncio.wait_for(self._session.send_ping(), timeout)
            return True
        except Exception:
            return False

    @property
    def tool_names(self) -> list[str]:
        return [t["function"]["name"] for t in self._tools]

    async def _call_tool(self, name: str, args: dict, employee_id: Optional[str]) -> tuple[bool, Any]:
        """Execute one tool through MCP. Returns (ok, parsed result); never raises."""
        # The signed-in employee may only read their own records.
        requested = args.get("employee_id")
        if employee_id and requested and requested != employee_id:
            return False, {"error": "not_authorized", "detail": "You can only access your own records."}
        if self._session is None:
            return False, {"error": "tool_unavailable", "detail": "MCP session is not connected"}
        try:
            result = await self._session.call_tool(name, args)
        except Exception as exc:  # server crashed, protocol error, bad arguments...
            return False, {"error": "tool_unavailable", "detail": f"{type(exc).__name__}: {exc}"}
        parsed: list[Any] = []
        for item in result.content:
            try:
                parsed.append(json.loads(item.text))
            except (json.JSONDecodeError, AttributeError):
                parsed.append(getattr(item, "text", str(item)))
        if result.isError:
            return False, {"error": "tool_error", "detail": str(parsed[0]) if parsed else ""}
        if name in LIST_TOOLS:
            return True, parsed
        return True, (parsed[0] if parsed else None)

    async def run(
        self, message: str, employee_id: Optional[str] = None, session_id: Optional[str] = None
    ) -> ChatResponse:
        start = time.perf_counter()
        trace: list[TraceStep] = []
        sources: dict[tuple[str, str], dict] = {}  # (doc_id, section lower) -> chunk
        employee_line = (
            f"The signed-in employee ID is {employee_id}."
            if employee_id
            else "No employee ID is available for this conversation."
        )
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(employee_line=employee_line)},
            {"role": "user", "content": message},
        ]

        def finish(answer: str, error: Optional[str] = None) -> ChatResponse:
            citations = self._citations(answer, sources)
            escalated = any(s.tool == ESCALATION_TOOL and s.ok for s in trace)
            return ChatResponse(
                answer=answer,
                citations=citations,
                tools_used=list(dict.fromkeys(s.tool for s in trace)),
                latency_ms=round((time.perf_counter() - start) * 1000, 1),
                error=error,
                trace=trace,
                escalated=escalated,
            )

        for _ in range(self._max_steps + 1):
            try:
                reply = await self._llm(messages, self._tools)
            except (APITimeoutError, APIError, LLMResponseError) as exc:
                log.warning(json.dumps({"session_id": session_id, "event": "llm_error", "error": str(exc)[:200]}))
                return finish(
                    "I couldn't reach the language model just now. Please try again in a moment.",
                    error=type(exc).__name__,
                )

            calls = getattr(reply, "tool_calls", None) or []
            if not calls:
                return finish((reply.content or "").strip())
            if len(trace) >= self._max_steps:
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments},
                        }
                        for c in calls
                    ],
                }
            )
            for call in calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                    ok, result = False, {"error": "invalid_arguments", "detail": call.function.arguments}
                    t0 = time.perf_counter()
                else:
                    t0 = time.perf_counter()
                    ok, result = await self._call_tool(name, args, employee_id)
                if ok:
                    self._collect_sources(name, result, sources)
                step = TraceStep(
                    step=len(trace) + 1,
                    tool=name,
                    arguments=args,
                    ok=ok and not (isinstance(result, dict) and "error" in result),
                    result_summary=_summarize(result),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                )
                trace.append(step)
                log.info(json.dumps({"session_id": session_id, "event": "tool_call", **step.model_dump()}))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result)[:TOOL_RESULT_CHAR_LIMIT],
                    }
                )

        return finish(
            "I wasn't able to finish working that out. Please rephrase or contact HR directly.",
            error="max_steps_exceeded",
        )

    @staticmethod
    def _collect_sources(tool: str, result: Any, sources: dict) -> None:
        chunks = result if tool == "search_policy_documents" else [result] if tool == "get_policy_section" else []
        for c in chunks:
            if isinstance(c, dict) and "doc_id" in c and "error" not in c:
                sources.setdefault((c["doc_id"], c["section"].lower()), c)

    @staticmethod
    def _citations(answer: str, sources: dict) -> list[Citation]:
        """Citations the answer makes that match a source a tool actually returned."""
        citations: dict[tuple[str, str], Citation] = {}
        normalized = answer.translate(_CITATION_MARKUP_NORMALIZE)
        for doc_id, section in CITATION_RE.findall(normalized):
            cited = section.strip().lower()
            candidates = [c for (d, _), c in sources.items() if d == doc_id]
            # Models often append detail ("PTO Request Process, section 4.3"), so match
            # when either section name contains the other. A bare [DOC_ID] cites the doc.
            chunk = next(
                (c for c in candidates if not cited or c["section"].lower() in cited or cited in c["section"].lower()),
                None,
            )
            if chunk is None:
                continue  # cited something no tool returned: not verifiable, so not listed
            k = (chunk["doc_id"], chunk["section"].lower())
            citations.setdefault(
                k,
                Citation(
                    doc_id=chunk["doc_id"],
                    title=chunk["title"],
                    section=chunk["section"],
                    source_file=chunk["source_file"],
                    snippet=_snippet(chunk["text"]),
                ),
            )
        return list(citations.values())


async def _cli(message: str, employee_id: Optional[str], transport: Optional[str] = None) -> None:
    async with HRAgent(transport=transport) as agent:
        r = await agent.run(message, employee_id=employee_id)
    print(f"\n{r.answer}\n")
    print(f"Citations: {[f'{c.doc_id}: {c.section}' for c in r.citations] or 'none'}")
    print(f"Escalated (mock ticket): {r.escalated}   Latency: {r.latency_ms} ms   Error: {r.error}")
    print("Trace:")
    for s in r.trace:
        outcome = "ok" if s.ok else "FAILED"
        print(f"  {s.step}. {s.tool}({json.dumps(s.arguments)}) -> {outcome} [{s.result_summary}] {s.duration_ms}ms")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message")
    parser.add_argument("--employee", default=None, help="signed-in employee id, e.g. E001")
    parser.add_argument(
        "--transport", choices=["stdio", "inmemory"], default=None,
        help="override MCP_TRANSPORT for this run (default: config.MCP_TRANSPORT, i.e. 'stdio')",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_cli(args.message, args.employee, args.transport))


if __name__ == "__main__":
    main()
