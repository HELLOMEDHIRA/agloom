"""Classifier MCP / observability routing: prompt rules and post-classify coercion."""

from __future__ import annotations

from agloom.classifier import (
    CLASSIFIER_PROMPT,
    coerce_analysis_for_mcp_observability,
    query_looks_like_observability_fetch,
)
from agloom.models import PatternType, QueryAnalysis


def test_classifier_prompt_mentions_mcp_observability_rule() -> None:
    assert "MCP / OBSERVABILITY RULE" in CLASSIFIER_PROMPT
    assert "Never REFLECTION" in CLASSIFIER_PROMPT or "Never" in CLASSIFIER_PROMPT


def test_query_looks_like_observability_fetch_positive() -> None:
    assert query_looks_like_observability_fetch("Investigate checkout errors in the last hour")
    assert query_looks_like_observability_fetch("Show me logs for the payment service")
    assert query_looks_like_observability_fetch("What caused the latency spike on Grafana?")


def test_query_looks_like_observability_fetch_skips_conceptual() -> None:
    assert not query_looks_like_observability_fetch("What is Grafana?")
    assert not query_looks_like_observability_fetch("What is p99 latency?")


def test_coerce_reflection_to_react_when_mcp_configured() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.REFLECTION,
        complexity=7,
        reasoning="reflection",
        subtasks=[],
        needs_reflection=True,
    )
    out = coerce_analysis_for_mcp_observability(
        analysis,
        "Investigate API errors in Loki",
        mcp_configured=True,
        has_tools=True,
    )
    assert out.pattern == PatternType.REACT
    assert out.subtasks == []
    assert out.needs_reflection is False


def test_coerce_direct_to_react_with_tools() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.DIRECT,
        complexity=2,
        reasoning="direct",
        direct_response="fake logs",
    )
    out = coerce_analysis_for_mcp_observability(
        analysis,
        "Fetch metrics for checkout latency",
        mcp_configured=False,
        has_tools=True,
    )
    assert out.pattern == PatternType.REACT
    assert out.direct_response is None


def test_coerce_noop_for_react_or_non_observability() -> None:
    analysis = QueryAnalysis(pattern=PatternType.REACT, complexity=4, reasoning="ok")
    out = coerce_analysis_for_mcp_observability(
        analysis,
        "Investigate errors",
        mcp_configured=True,
        has_tools=True,
    )
    assert out.pattern == PatternType.REACT

    reflection = QueryAnalysis(pattern=PatternType.REFLECTION, complexity=7, reasoning="lit review")
    out2 = coerce_analysis_for_mcp_observability(
        reflection,
        "Write a rigorous literature review on transformers",
        mcp_configured=True,
        has_tools=True,
    )
    assert out2.pattern == PatternType.REFLECTION
