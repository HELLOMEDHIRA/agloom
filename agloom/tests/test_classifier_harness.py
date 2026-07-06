"""Classifier harness planning fields."""

from __future__ import annotations

from agloom.src.classifier import HARNESS_CLASSIFIER_SECTION, build_classifier_user_prompt
from agloom.src.models import HarnessPlanTask, PatternType, QueryAnalysis, query_analysis_from_tool_payload
from agloom.src.models import QueryAnalysisToolPayload


def test_harness_classifier_section_mentions_harness_rule() -> None:
    assert "HARNESS RULE" in HARNESS_CLASSIFIER_SECTION
    assert "harness_plan" in HARNESS_CLASSIFIER_SECTION
    assert "harness_work_kind" in HARNESS_CLASSIFIER_SECTION


def test_build_classifier_user_prompt_injects_harness_section_when_needed() -> None:
    with_plan = build_classifier_user_prompt(tools_desc="none", query="investigate outage", harness_needs_plan=True)
    without_plan = build_classifier_user_prompt(tools_desc="none", query="investigate outage", harness_needs_plan=False)
    assert "HARNESS RULE" in with_plan
    assert "HARNESS RULE" not in without_plan


def test_query_analysis_wire_includes_harness_plan() -> None:
    raw = QueryAnalysisToolPayload(
        pattern="REACT",
        complexity="4",
        reasoning="rca",
        harness_work_kind="investigation",
        harness_plan=[
            HarnessPlanTask(
                task_id="step-1",
                description="Gather logs",
                category="evidence",
                priority="high",
                verification_steps=["Logs collected"],
            )
        ],
    )
    analysis = query_analysis_from_tool_payload(raw, tools_available=True)
    assert analysis.pattern == PatternType.REACT
    assert analysis.harness_work_kind == "investigation"
    assert len(analysis.harness_plan) == 1
    assert analysis.harness_plan[0].task_id == "step-1"
    assert analysis.subtasks == []
