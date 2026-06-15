"""Post-classify coercion and tool-required query heuristics."""

from __future__ import annotations

from agloom.classifier import (
    coerce_analysis_when_tools_required,
    query_is_purely_conceptual,
    query_needs_registered_tools,
)
from agloom.models import PatternType, QueryAnalysis, SubTask


def test_query_needs_registered_tools_observability() -> None:
    assert query_needs_registered_tools("Investigate checkout errors in logs")


def test_query_needs_registered_tools_files() -> None:
    assert query_needs_registered_tools("Read the first 50 lines of pyproject.toml")


def test_query_needs_registered_tools_memory() -> None:
    assert query_needs_registered_tools("Remember that my name is Ada")


def test_query_needs_registered_tools_skips_conceptual() -> None:
    assert not query_needs_registered_tools("What is Grafana?")
    assert query_is_purely_conceptual("What is Python?")


def test_query_needs_registered_tools_skips_literature_review() -> None:
    assert not query_needs_registered_tools("Write a rigorous literature review on transformers")


def test_coerce_direct_and_reflection_to_react() -> None:
    for pattern in (PatternType.DIRECT, PatternType.REFLECTION):
        analysis = QueryAnalysis(
            pattern=pattern,
            complexity=5,
            reasoning="x",
            direct_response="fake" if pattern == PatternType.DIRECT else None,
        )
        out = coerce_analysis_when_tools_required(
            analysis,
            "Show me logs for payment service",
            has_tools=True,
        )
        assert out.pattern == PatternType.REACT


def test_coerce_supervisor_when_subtasks_have_no_required_tools() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.SUPERVISOR,
        complexity=6,
        reasoning="supervisor",
        subtasks=[
            SubTask(worker_id="w1", task="Fetch metrics", required_tools=[]),
            SubTask(worker_id="w2", task="Summarize", required_tools=[]),
        ],
    )
    out = coerce_analysis_when_tools_required(
        analysis,
        "Fetch metrics for checkout",
        has_tools=True,
    )
    assert out.pattern == PatternType.REACT
    assert out.subtasks == []


def test_coerce_noop_when_subtasks_list_required_tools() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.SUPERVISOR,
        complexity=6,
        reasoning="supervisor",
        subtasks=[
            SubTask(worker_id="w1", task="Research A", required_tools=["search_logs"]),
        ],
    )
    out = coerce_analysis_when_tools_required(
        analysis,
        "Fetch metrics for checkout",
        has_tools=True,
    )
    assert out.pattern == PatternType.SUPERVISOR
