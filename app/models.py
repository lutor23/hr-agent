"""Request/response models shared by the retriever, agent and API."""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class Citation(BaseModel):
    doc_id: str  # e.g. "POL-HR-001"
    title: str
    section: str
    source_file: str
    snippet: Optional[str] = None  # excerpt of the cited text


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    employee_id: Optional[str] = Field(default=None, max_length=32)  # e.g. "E001"
    session_id: Optional[str] = Field(default=None, max_length=64)  # for trace correlation


class TraceStep(BaseModel):
    """One MCP tool call made by the agent (operational trace, not model reasoning)."""

    step: int
    tool: str
    arguments: dict[str, Any]
    ok: bool
    result_summary: str
    duration_ms: float


class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]
    tools_used: List[str]
    latency_ms: float
    error: Optional[str] = None  # set when the answer is partial (e.g. LLM timeout)
    trace: List[TraceStep] = []  # tool calls in order (agent only)
    escalated: bool = False  # True if the agent opened a (mock) HR ticket


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    chroma_docs: int  # number of indexed chunks
    version: str
    mcp_connected: bool = False  # MCP server subprocess answers a ping
    mcp_tools: int = 0  # tools discovered over MCP
