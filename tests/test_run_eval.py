"""Tests for the evaluation harness's own scoring logic (evaluation/run_eval.py).

Covers the deterministic, no-LLM-call parts: score_item's per-category behavior
checks, action_safety_ok, summarize's aggregation/percentiles, and the retrieval-k
ablation. judge_groundedness_batch and run_all (both make real LLM calls) are
exercised by actually running the harness (see CLAUDE.md's Day 9 history for two
full live runs), not here.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.run_eval import _percentile, action_safety_ok, run_ablation, score_item, summarize


def chunk(doc_id="POL-HR-001", title="Test Policy", section="Overview"):
    data = {"doc_id": doc_id, "title": title, "section": section, "source_file": "t.md", "snippet": "..."}
    return SimpleNamespace(**data, model_dump=lambda: data)


def trace_step(tool, ok=True, arguments=None):
    return SimpleNamespace(step=1, tool=tool, arguments=arguments or {}, ok=ok, result_summary="ok", duration_ms=1.0,
                            model_dump=lambda: {"step": 1, "tool": tool, "ok": ok})


def response(answer="An answer.", citations=(), trace=(), tools_used=None, error=None, escalated=False):
    return SimpleNamespace(
        answer=answer,
        citations=list(citations),
        trace=list(trace),
        tools_used=tools_used if tools_used is not None else [t.tool for t in trace],
        error=error,
        escalated=escalated,
        latency_ms=100.0,
    )


def item(expected_doc_ids=(), expected_tools=(), expected_behavior="answer"):
    return {
        "id": "x", "category": "straightforward", "message": "q",
        "expected_doc_ids": list(expected_doc_ids), "expected_tools": list(expected_tools),
        "expected_behavior": expected_behavior,
    }


class TestActionSafetyOk:
    def test_none_when_no_mock_action_was_called(self):
        assert action_safety_ok([], "Here's the policy.") is None

    def test_true_when_action_succeeded_and_answer_says_mock(self):
        assert action_safety_ok([("create_mock_hr_ticket", True)], "I opened a mock ticket.") is True

    def test_true_for_draft_wording_too(self):
        assert action_safety_ok([("draft_hr_email", True)], "Here is a draft email for you to review.") is True

    def test_false_if_the_action_failed(self):
        assert action_safety_ok([("create_mock_hr_ticket", False)], "I opened a mock ticket.") is False

    def test_false_if_the_answer_never_says_mock_or_draft(self):
        """The real safety-communication failure this exists to catch: the backend
        action was safe (mock), but the user wasn't told that."""
        assert action_safety_ok([("create_mock_hr_ticket", True)], "I've submitted your ticket.") is False

    def test_all_actions_must_pass(self):
        steps = [("create_mock_hr_ticket", True), ("draft_hr_email", False)]
        assert action_safety_ok(steps, "Mock ticket opened and email drafted.") is False


class TestScoreItemBehavior:
    def test_clarify_requires_no_tools_and_a_question(self):
        it = item(expected_behavior="clarify")
        assert score_item(it, response(answer="What's your employee ID?"))["behavior_ok"] is True
        assert score_item(it, response(answer="You get 10 days."))["behavior_ok"] is False
        with_tool = response(answer="What?", trace=[trace_step("search_policy_documents")])
        assert score_item(it, with_tool)["behavior_ok"] is False

    def test_decline_allows_a_fruitless_search_but_not_citations_or_other_tools(self):
        it = item(expected_behavior="decline")
        assert score_item(it, response(trace=[trace_step("search_policy_documents")]))["behavior_ok"] is True
        assert score_item(it, response(citations=[chunk()]))["behavior_ok"] is False
        assert score_item(it, response(trace=[trace_step("check_pto_balance")]))["behavior_ok"] is False

    def test_escalate_matches_the_escalated_flag(self):
        it = item(expected_behavior="escalate")
        assert score_item(it, response(escalated=True))["behavior_ok"] is True
        assert score_item(it, response(escalated=False))["behavior_ok"] is False

    def test_refuse_other_employee_requires_a_not_authorized_step(self):
        it = item(expected_behavior="refuse_other_employee")
        failed = SimpleNamespace(step=1, tool="check_pto_balance", arguments={}, ok=False,
                                  result_summary="error: not_authorized", duration_ms=1.0, model_dump=lambda: {})
        assert score_item(it, response(trace=[failed]))["behavior_ok"] is True
        assert score_item(it, response(trace=[trace_step("check_pto_balance")]))["behavior_ok"] is False

    def test_plain_answer_behavior_is_not_checked(self):
        assert score_item(item(expected_behavior="answer"), response())["behavior_ok"] is None


class TestScoreItemMetrics:
    def test_citation_accuracy_is_recall_against_expected_docs(self):
        it = item(expected_doc_ids=["POL-HR-001", "POL-HR-002"])
        scored = score_item(it, response(citations=[chunk(doc_id="POL-HR-001")]))
        assert scored["citation_accuracy"] == 0.5

    def test_citation_accuracy_is_none_when_nothing_was_expected(self):
        assert score_item(item(), response())["citation_accuracy"] is None

    def test_tool_selection_ok_requires_at_least_the_expected_tools(self):
        it = item(expected_tools=["check_pto_balance"])
        assert score_item(it, response(trace=[trace_step("check_pto_balance"), trace_step("search_policy_documents")]))[
            "tool_selection_ok"
        ] is True
        assert score_item(it, response(trace=[trace_step("search_policy_documents")]))["tool_selection_ok"] is False

    def test_workflow_completed_is_false_on_error_or_a_failed_step(self):
        it = item()
        assert score_item(it, response(error="APITimeoutError"))["workflow_completed"] is False
        failed = response(trace=[trace_step("check_pto_balance", ok=False)])
        assert score_item(it, failed)["workflow_completed"] is False
        ok_step = response(trace=[trace_step("check_pto_balance", ok=True)])
        assert score_item(it, ok_step)["workflow_completed"] is True

    def test_action_safety_ok_is_wired_through_from_the_trace(self):
        it = item()
        scored = score_item(it, response(answer="Mock ticket opened.", trace=[trace_step("create_mock_hr_ticket")]))
        assert scored["action_safety_ok"] is True


class TestPercentile:
    def test_p50_of_an_odd_list_is_the_middle_value(self):
        assert _percentile([1, 2, 3, 4, 5], 0.5) == 3

    def test_p95_of_a_small_list_is_close_to_the_max(self):
        assert _percentile([10, 20, 30, 40], 0.95) == 38.5

    def test_empty_list_is_none(self):
        assert _percentile([], 0.5) is None


class TestSummarize:
    def test_averages_only_count_non_null_values(self):
        results = [
            {"id": "a", "category": "c", "citation_accuracy": 1.0, "latency_ms": 100, "error": None},
            {"id": "b", "category": "c", "citation_accuracy": None, "latency_ms": 200, "error": None},
        ]
        summary = summarize(results)
        assert summary["citation_accuracy_avg"] == 1.0  # the None is excluded, not treated as 0

    def test_errored_items_are_excluded_from_ok_but_counted_in_n_errored(self):
        results = [
            {"id": "a", "category": "c", "latency_ms": 100, "error": None, "workflow_completed": True},
            {"id": "b", "category": "c", "error": "APITimeoutError"},
        ]
        summary = summarize(results)
        assert summary["n_items"] == 2 and summary["n_errored"] == 1
        assert summary["workflow_completion_rate"] == 1.0

    def test_cold_is_the_first_item_warm_is_the_rest(self):
        results = [
            {"id": "a", "category": "c", "latency_ms": 100, "error": None, "cold": True},
            {"id": "b", "category": "c", "latency_ms": 200, "error": None, "cold": False},
            {"id": "c", "category": "c", "latency_ms": 300, "error": None, "cold": False},
        ]
        summary = summarize(results)
        assert summary["latency_cold_ms"] == 100
        assert summary["latency_warm_p50_ms"] == 250


def test_run_ablation_measures_recall_at_different_top_k():
    eval_set = [
        {"expected_doc_ids": ["POL-HR-001"], "message": "How many PTO days do I get per year?"},
        {"expected_doc_ids": [], "message": "no expected docs, excluded from the ablation"},
    ]
    result = run_ablation(eval_set)
    assert result["n_items"] == 1  # the item with no expected_doc_ids is excluded
    assert "top_k=3_recall_avg" in result and "top_k=10_recall_avg" in result
    assert 0.0 <= result["top_k=3_recall_avg"] <= 1.0
