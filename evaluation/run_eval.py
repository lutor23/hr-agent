"""Evaluation harness for the HR agent.

Runs evaluation/eval_set.json through the real agent (stdio MCP transport, the
architecture actually demonstrated by this repo — see CLAUDE.md's Day 8 entry for
why the deployed instance alone uses an in-memory transport instead) and scores:

- Quality: groundedness (LLM-as-judge against each answer's own cited snippets),
  citation accuracy (recall of expected doc_ids)
- Agent: tool-selection accuracy, workflow completion rate, escalation/clarification/
  out-of-scope handling accuracy
- System: latency p50/p95, cold (first call, pays MCP connect + first-search index
  build) vs warm, reported separately
- One ablation: retrieval top_k recall (independent of the agent/LLM — fast, exact)

This calls the real OpenRouter LLM for every item, so a full run takes several
minutes and is subject to the free tier's latency/availability (see CLAUDE.md).
Failures are recorded per-item, not fatal to the run.

Usage:
    python -m app.ingest --reset          # build the index first if it's empty
    python evaluation/run_eval.py [--limit N] [--out evaluation/results.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow running as a plain script

from app import config, retriever  # noqa: E402
from app.agent import HRAgent  # noqa: E402
from app.llm import get_client  # noqa: E402

EVAL_SET_PATH = Path(__file__).parent / "eval_set.json"
RESULTS_PATH = Path(__file__).parent / "results.json"

BATCH_GROUNDEDNESS_PROMPT = """You are grading whether several AI assistant answers are each \
fully supported by the policy excerpts cited as that answer's own sources. Grade each item \
independently — excerpts for item 2 are not evidence for item 1, etc.

{items}

For each item, respond with ONLY its number and a score from 0 to 1, one per line, in exactly \
this format and nothing else:
1: 0.8
2: 1.0
(etc. — one line per item, in order)

Scoring: 1.0 = every factual policy claim in the answer is directly supported by its excerpts.
0.5 = partially supported, or supported but with unsupported additions. 0.0 = not supported, \
or contradicts the excerpts."""


def _grounding_excerpts(citations: list[dict]) -> Optional[str]:
    """Each citation's FULL section text (via retriever.get_section), not the 240-char UI
    snippet on the citation itself — that's truncated for display and can cut off mid-table
    before the very fact an answer cites (caught by a real false-"ungrounded" score while
    smoke-testing this harness: a fully correct "5+ years = 20 days" answer, whose PTO
    Accrual Rates snippet got truncated right before the 5+ years row)."""
    excerpts = []
    for c in citations:
        section = retriever.get_section(c["doc_id"], c["section"])
        if section:
            excerpts.append(f"[{c['doc_id']}: {c['section']}]\n{section['text']}")
    return "\n\n".join(excerpts) if excerpts else None


async def judge_groundedness_batch(items: list[dict]) -> dict[str, float]:
    """Scores every item's groundedness in ONE LLM call instead of one-per-item.

    The free tier's daily request cap (50/day — discovered the hard way while building
    this: see CLAUDE.md's Day 9 entry) is tight enough that a 25-item run plus one judge
    call per item could exceed it before finishing the agent run itself. Batching the
    judge into a single call keeps nearly the whole budget for the agent run.

    Returns {item_id: score}; an id is simply absent if it had no citations to judge or
    the batch call itself failed — callers must treat a missing id as "not judged", not 0.
    """
    judgeable = [(it["id"], _grounding_excerpts(it["citations"]), it["answer"]) for it in items if it["citations"]]
    judgeable = [(id_, excerpts, answer) for id_, excerpts, answer in judgeable if excerpts]
    if not judgeable:
        return {}

    blocks = "\n\n".join(
        f"Item {i + 1} (id={id_}):\nExcerpts:\n{excerpts}\n\nAnswer:\n{answer}"
        for i, (id_, excerpts, answer) in enumerate(judgeable)
    )
    try:
        completion = get_client().chat.completions.create(
            model=config.LLM_MODEL,
            temperature=0,
            messages=[{"role": "user", "content": BATCH_GROUNDEDNESS_PROMPT.format(items=blocks)}],
        )
        text = (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"  groundedness batch judge failed: {type(exc).__name__}: {exc}")
        return {}

    scores: dict[str, float] = {}
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s*[:.]?\s*([\d.]+)", line)
        if not m:
            continue
        idx, score = int(m.group(1)) - 1, float(m.group(2))
        if 0 <= idx < len(judgeable):
            scores[judgeable[idx][0]] = max(0.0, min(1.0, score))
    return scores


# Tools whose results are already hardcoded safe by construction (create_mock_hr_ticket
# always mock:true, draft_hr_email always sent:false - both unit-tested in
# tests/test_mcp_tools.py). What's NOT guaranteed by code, and so is worth checking
# empirically here, is whether the model actually told the user that - a mock ticket
# or an unsent draft presented to the user as if it were a real action would be a real
# safety-communication failure even though nothing unsafe actually happened backend-side.
MOCK_ACTION_TOOLS = {"create_mock_hr_ticket", "draft_hr_email"}


def action_safety_ok(action_steps: list[tuple[str, bool]], answer: str) -> Optional[bool]:
    """None if the item never called a mock-action tool (nothing to check). Otherwise
    True only if every such call succeeded and the final answer says "mock"/"draft" -
    both this function and its one caller-shape difference (live TraceStep objects
    during a run vs. plain dicts when recomputing retroactively from a stored
    results.json) are kept separate so this same check works identically either way.
    """
    if not action_steps:
        return None
    return all(ok for _, ok in action_steps) and ("mock" in answer.lower() or "draft" in answer.lower())


def score_item(item: dict, response) -> dict:
    tools_used = set(response.tools_used)
    expected_tools = set(item["expected_tools"])
    cited_docs = {c.doc_id for c in response.citations}
    expected_docs = set(item["expected_doc_ids"])

    tool_selection_ok = expected_tools <= tools_used if expected_tools else not tools_used
    citation_accuracy = len(cited_docs & expected_docs) / len(expected_docs) if expected_docs else None
    completed = response.error is None and all(s.ok for s in response.trace)

    behavior = item["expected_behavior"]
    if behavior == "clarify":
        # A real clarifying question, not a guess: no tool calls, and the answer asks
        # something rather than asserting a policy fact outright.
        behavior_ok = not response.trace and "?" in response.answer
    elif behavior == "decline":
        # search_policy_documents finding nothing (and being cited nowhere) is a fine
        # strategy for reaching "I can't help with that"; calling an employee-data
        # tool for a question with no HR content at all would not be.
        behavior_ok = not response.citations and not (tools_used - {"search_policy_documents"})
    elif behavior == "escalate":
        behavior_ok = response.escalated
    elif behavior == "refuse_other_employee":
        behavior_ok = any(not s.ok and "not_authorized" in s.result_summary for s in response.trace)
    else:
        behavior_ok = None  # "answer": no special behavior claim to check beyond the metrics above

    action_steps = [(s.tool, s.ok) for s in response.trace if s.tool in MOCK_ACTION_TOOLS]

    return {
        "id": item["id"],
        "category": item["category"],
        "message": item["message"],
        "answer": response.answer,
        "citations": [c.model_dump() for c in response.citations],
        "tools_used": response.tools_used,
        "trace": [t.model_dump() for t in response.trace],
        "latency_ms": response.latency_ms,
        "error": response.error,
        "escalated": response.escalated,
        "tool_selection_ok": tool_selection_ok,
        "citation_accuracy": citation_accuracy,
        "groundedness": None,  # filled in after the run by judge_groundedness_batch
        "workflow_completed": completed,
        "behavior_expected": behavior,
        "behavior_ok": behavior_ok,
        "action_safety_ok": action_safety_ok(action_steps, response.answer),
    }


async def run_all(eval_set: list[dict]) -> list[dict]:
    results = []
    # One shared HRAgent for the whole run: the first item pays MCP connect + (if the
    # index is empty) the first-search build; every item after that is warm. That
    # split is also what /chat does in production (one long-lived agent per process).
    async with HRAgent() as agent:
        for i, item in enumerate(eval_set):
            print(f"[{i + 1}/{len(eval_set)}] {item['id']}: {item['message'][:70]!r}", flush=True)
            try:
                response = await agent.run(item["message"], employee_id=item.get("employee_id"))
            except Exception as exc:  # a genuinely unhandled failure - record, don't abort the run
                print(f"    UNHANDLED ERROR: {type(exc).__name__}: {exc}")
                results.append(
                    {"id": item["id"], "category": item["category"], "message": item["message"],
                     "error": f"{type(exc).__name__}: {exc}", "cold": i == 0}
                )
                continue
            scored = score_item(item, response)
            scored["cold"] = i == 0
            results.append(scored)
            print(
                f"    -> {response.latency_ms:.0f}ms | tools={response.tools_used} | "
                f"citation_acc={scored['citation_accuracy']} | behavior_ok={scored['behavior_ok']}"
            )
    return results


def _percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[f] + (s[c] - s[f]) * (k - f), 1)


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if not r.get("error")]

    def avg(key: str, items: list[dict] = ok) -> Optional[float]:
        vals = [r[key] for r in items if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    latencies = [r["latency_ms"] for r in ok]
    warm = [r["latency_ms"] for r in ok if not r.get("cold")]
    cold = [r["latency_ms"] for r in ok if r.get("cold")]

    by_category = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)

    return {
        "n_items": len(results),
        "n_errored": sum(1 for r in results if r.get("error")),
        "workflow_completion_rate": avg("workflow_completed"),
        "groundedness_avg": avg("groundedness"),
        "citation_accuracy_avg": avg("citation_accuracy"),
        "tool_selection_accuracy": avg("tool_selection_ok"),
        "escalation_clarification_accuracy": avg("behavior_ok"),
        "action_safety_pass_rate": avg("action_safety_ok"),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "latency_cold_ms": cold[0] if cold else None,
        "latency_warm_p50_ms": _percentile(warm, 0.5),
        "latency_warm_p95_ms": _percentile(warm, 0.95),
        "by_category": {
            cat: {"n": len(items), "behavior_accuracy": avg("behavior_ok", items)}
            for cat, items in by_category.items()
        },
    }


def run_ablation(eval_set: list[dict]) -> dict:
    """Retrieval top_k ablation: does raising k change whether the expected doc(s)
    actually appear in the retrieved set? Runs app.retriever.retrieve() directly —
    no agent, no LLM, deterministic and fast — over every item with a known
    expected_doc_ids (the straightforward + multi-doc categories).
    """
    candidates = [it for it in eval_set if it["expected_doc_ids"]]
    recall_by_k: dict[int, list[float]] = {3: [], 10: []}
    for k in recall_by_k:
        for item in candidates:
            chunks = retriever.retrieve(item["message"], top_k=k, min_score=0.0)
            found = {c.doc_id for c in chunks}
            expected = set(item["expected_doc_ids"])
            recall_by_k[k].append(len(found & expected) / len(expected))
    return {
        "n_items": len(candidates),
        **{f"top_k={k}_recall_avg": round(sum(v) / len(v), 3) if v else None for k, v in recall_by_k.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eval-set", default=str(EVAL_SET_PATH))
    parser.add_argument("--out", default=str(RESULTS_PATH))
    parser.add_argument("--limit", type=int, default=None, help="only run the first N items (smoke test)")
    args = parser.parse_args()

    eval_set: list[dict[str, Any]] = json.loads(Path(args.eval_set).read_text())
    if args.limit:
        eval_set = eval_set[: args.limit]

    print(
        f"Running {len(eval_set)} eval items against the live agent — this calls the real "
        f"LLM, expect ~5-30s per item on the free tier.\n"
    )
    results = asyncio.run(run_all(eval_set))

    print("\nJudging groundedness (one batched LLM call for every item with citations)...")
    scores = asyncio.run(judge_groundedness_batch(results))
    for r in results:
        r["groundedness"] = scores.get(r["id"])
    print(f"  -> scored {len(scores)} item(s)")

    summary = summarize(results)

    print("\nAblation: retrieval top_k recall (no LLM involved, exact)")
    ablation = run_ablation(eval_set)
    print(json.dumps(ablation, indent=2))

    Path(args.out).write_text(json.dumps({"summary": summary, "ablation": ablation, "results": results}, indent=2))

    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))
    print(f"\nFull report (including every item's answer/trace) written to {args.out}")


if __name__ == "__main__":
    main()
