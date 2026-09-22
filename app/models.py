"""Request/response models shared by the retriever, agent and API."""

from typing import List, Optional

from pydantic import BaseModel


class Citation(BaseModel):
    doc_id: str  # e.g. "POL-HR-001"
    title: str
    section: str
    source_file: str


class ChatRequest(BaseModel):
    message: str
    employee_id: Optional[str] = None  # e.g. "E001" for personalized answers
    session_id: Optional[str] = None  # for trace correlation


class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]
    tools_used: List[str]
    latency_ms: float
    error: Optional[str] = None  # set when the answer is partial (e.g. LLM timeout)


class HealthResponse(BaseModel):
    status: str  # "ok"
    chroma_docs: int  # number of indexed chunks
    version: str
