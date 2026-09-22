"""RAG: retrieve policy chunks, build a grounded prompt, and answer with citations."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import List, Optional

from openai import APIError, APITimeoutError, OpenAI

from app import config, employee_data
from app.ingest import get_collection
from app.loaders import Chunk
from app.models import ChatResponse, Citation

log = logging.getLogger(__name__)

# Cosine similarity below this means the query isn't covered by any policy.
MIN_SCORE = 0.25
NO_ANSWER = "I couldn't find a policy covering that. Please contact HR for help."

SYSTEM_PROMPT = """You are the Acme Corp HR Policy Assistant. Answer employee questions \
using ONLY the numbered policy excerpts provided.
- Cite every claim with the excerpt number in square brackets, e.g. [1] or [2][3].
- If the excerpts do not contain the answer, say you couldn't find a policy covering it. \
Never guess or use outside knowledge.
- If employee details are provided, use them to personalize the answer, but policy \
statements still need citations.
- Be concise and specific: include numbers, deadlines and steps from the policy."""


@dataclass
class RetrievedChunk(Chunk):
    score: float = 0.0  # cosine similarity, 1.0 = identical


def retrieve(
    query: str, top_k: int = 5, doc_id: Optional[str] = None, min_score: float = MIN_SCORE
) -> List[RetrievedChunk]:
    """Top-k policy chunks for a query, best first, dropping chunks below min_score.

    Results come from across all documents unless doc_id restricts the search.
    """
    collection = get_collection()
    res = collection.query(
        query_texts=[query],
        n_results=top_k,
        where={"doc_id": doc_id} if doc_id else None,
        include=["documents", "metadatas", "distances"],
    )
    chunks = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        score = 1.0 - dist
        if score < min_score:
            continue
        # Stored documents are "<title> - <section>\n<text>"; strip the heading line.
        text = doc.split("\n", 1)[1] if "\n" in doc else doc
        chunks.append(RetrievedChunk(text=text, score=round(score, 4), **meta))
    return chunks


def employee_context(employee_id: str) -> Optional[str]:
    """Plain-text summary of an employee's record, or None if the id is unknown."""
    emp = employee_data.get_employee(employee_id)
    if emp is None:
        return None
    lines = [
        f"{emp['name']} ({emp['employee_id']}), {emp['title']}, {emp['department']}",
        f"Hired {emp['hire_date']}; {emp['employment_type']}; {emp['work_arrangement']}; "
        f"based in {emp['location']}",
    ]
    if pto := employee_data.get_pto_balance(employee_id):
        lines.append(
            f"PTO: {pto['available_hours']}h available, {pto['pending_hours']}h pending, "
            f"{pto['used_hours']}h used this year ({pto['annual_days']} days/yr)"
        )
    if ben := employee_data.get_benefits(employee_id):
        lines.append(
            f"Benefits: {ben['medical_plan'] or 'no medical plan'} "
            f"({ben['coverage_tier'] or 'n/a'}), status: {ben['enrollment_status']}"
        )
    return "\n".join(lines)


def build_prompt(
    query: str, chunks: List[RetrievedChunk], employee_context: Optional[str] = None
) -> str:
    """User-turn prompt: numbered excerpts, optional employee details, then the question."""
    excerpts = "\n\n".join(
        f"[{i}] {c.title} ({c.doc_id}), section \"{c.section}\":\n{c.text}"
        for i, c in enumerate(chunks, start=1)
    )
    parts = [f"Policy excerpts:\n\n{excerpts}"]
    if employee_context:
        parts.append(f"Employee details:\n{employee_context}")
    parts.append(f"Question: {query}")
    return "\n\n".join(parts)


def extract_citations(answer: str, chunks: List[RetrievedChunk]) -> List[Citation]:
    """Citations for the excerpts the answer references, de-duplicated by doc+section.

    If the model used no [n] markers, fall back to the retrieved sources so the
    caller still sees what was consulted.
    """
    used = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
    picked = [chunks[n - 1] for n in dict.fromkeys(used) if 1 <= n <= len(chunks)] or chunks
    seen, citations = set(), []
    for c in picked:
        key = (c.doc_id, c.section)
        if key not in seen:
            seen.add(key)
            citations.append(
                Citation(doc_id=c.doc_id, title=c.title, section=c.section, source_file=c.source_file)
            )
    return citations


def ask(query: str, employee_id: Optional[str] = None, top_k: int = 5) -> ChatResponse:
    start = time.perf_counter()

    def respond(answer: str, citations=(), error: Optional[str] = None) -> ChatResponse:
        return ChatResponse(
            answer=answer,
            citations=list(citations),
            tools_used=["search_policy_documents"],
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            error=error,
        )

    chunks = retrieve(query, top_k=top_k)
    if not chunks:
        return respond(NO_ANSWER)

    context = None
    if employee_id:
        context = employee_context(employee_id)
        if context is None:
            return respond(f"I couldn't find an employee with ID {employee_id}.", error="unknown_employee")

    client = OpenAI(
        api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL,
        timeout=config.LLM_TIMEOUT_S, max_retries=1,
    )
    try:
        completion = client.chat.completions.create(
            model=config.LLM_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(query, chunks, context)},
            ],
        )
    except (APITimeoutError, APIError) as exc:
        log.warning("LLM call failed: %s", exc)
        # Partial answer: the retrieved policy text without LLM synthesis.
        top = chunks[0]
        return respond(
            f"I couldn't generate a full answer right now. Most relevant policy "
            f"({top.title}, {top.section}):\n{top.text}",
            extract_citations("", chunks[:1]),
            error=type(exc).__name__,
        )

    answer = (completion.choices[0].message.content or "").strip()
    return respond(answer, extract_citations(answer, chunks))
