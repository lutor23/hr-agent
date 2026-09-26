"""FastAPI app: chat API + minimal chat UI over the MCP-backed HR agent.

    uvicorn app.main:app --port 8000

One long-lived HRAgent (one MCP server subprocess) is started with the app and shared
by all requests, so the embedding model is loaded once instead of once per question.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app import config, employee_data
from app.agent import HRAgent, LLMFn
from app.ingest import count_chunks
from app.models import ChatRequest, ChatResponse, HealthResponse

VERSION = "0.1.0"
CHAT_TIMEOUT_S = 90.0  # whole-request budget; each LLM call also has its own 30s timeout
INDEX_HTML = config.ROOT / "app" / "static" / "index.html"

log = logging.getLogger("hr_agent.api")


def _enable_trace_logging() -> None:
    trace_log = logging.getLogger("hr_agent.trace")
    if not trace_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s TRACE %(message)s"))
        trace_log.addHandler(handler)
    trace_log.setLevel(logging.INFO)
    trace_log.propagate = False


def create_app(llm_fn: Optional[LLMFn] = None) -> FastAPI:
    """App factory. `llm_fn` swaps the agent's LLM (tests use a scripted fake)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _enable_trace_logging()
        agent = HRAgent(llm_fn=llm_fn)
        app.state.agent = agent
        app.state.startup_error = None
        try:
            await agent.connect()
        except Exception as exc:  # app still starts; /health reports degraded, /chat 503s
            app.state.startup_error = f"{type(exc).__name__}: {exc}"
            log.error("MCP server failed to start: %s", app.state.startup_error)
        try:
            yield
        finally:
            await agent.close()

    app = FastAPI(title="Acme HR Policy Assistant", version=VERSION, lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(INDEX_HTML)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> JSONResponse:
        agent: HRAgent = app.state.agent
        chroma_docs = await asyncio.to_thread(count_chunks)
        mcp_ok = await agent.ping()
        body = HealthResponse(
            status="ok" if chroma_docs > 0 and mcp_ok else "degraded",
            chroma_docs=chroma_docs,
            version=VERSION,
            mcp_connected=mcp_ok,
            mcp_tools=len(agent.tool_names) if mcp_ok else 0,
        )
        return JSONResponse(body.model_dump(), status_code=200 if body.status == "ok" else 503)

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        agent: HRAgent = app.state.agent
        if await asyncio.to_thread(count_chunks) == 0:
            raise HTTPException(503, "The policy index is empty. Run `python -m app.ingest --reset` first.")
        if not await agent.ping():
            raise HTTPException(503, "The MCP tool server is unavailable. Try again shortly.")
        try:
            return await asyncio.wait_for(
                agent.run(req.message, employee_id=req.employee_id, session_id=req.session_id),
                CHAT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            log.warning(json.dumps({"session_id": req.session_id, "event": "chat_timeout"}))
            raise HTTPException(504, "The request took too long. Please try again.") from None

    @app.get("/employees", include_in_schema=False)
    def employees() -> list[dict]:
        """Mock signed-in-employee choices for the demo UI (id + name only)."""
        return [
            {"employee_id": e["employee_id"], "name": e["name"]} for e in employee_data.list_employees()
        ]

    return app


app = create_app()
