"""Tests for shared classifier helpers in ``unified_agent``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agloom.models import PatternType, QueryAnalysis
from agloom.unified_agent import (
    _build_classifier_augmented_query,
    _build_harness_context_for_classify,
    _coerce_unknown_pattern_handler,
    _execute_analyze_query,
)
from agloom.unified_agent import _HANDLERS


def test_build_classifier_augmented_query_neither() -> None:
    assert _build_classifier_augmented_query(memory_ctx="", harness_ctx="", processed_query="Q") == "Q"


def test_build_classifier_augmented_query_memory_only() -> None:
    assert _build_classifier_augmented_query(memory_ctx="M", harness_ctx="", processed_query="Q") == "M\nQ"


def test_build_classifier_augmented_query_harness_only() -> None:
    out = _build_classifier_augmented_query(memory_ctx="", harness_ctx="H", processed_query="Q")
    assert "=== CROSS-SESSION PROGRESS ===" in out
    assert "H" in out
    assert out.endswith("\nQ")


def test_build_classifier_augmented_query_memory_and_harness() -> None:
    out = _build_classifier_augmented_query(memory_ctx="M", harness_ctx="H", processed_query="Q")
    assert out.startswith("M")
    assert "CROSS-SESSION PROGRESS" in out
    assert out.endswith("Q")


@pytest.mark.asyncio
async def test_execute_analyze_query_forwards_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_analyze_query(**kwargs: object) -> QueryAnalysis:
        captured.update(kwargs)
        return QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="ok", subtasks=[])

    monkeypatch.setattr("agloom.unified_agent.analyze_query", fake_analyze_query)

    cfg = {
        "llm": object(),
        "tools": ["t1"],
        "classifier_timeout": 9.0,
        "structured_max_retries": 1,
        "fallback_pattern": None,
    }
    r = await _execute_analyze_query(cfg, augmented_query="aq", skill_context="sk")
    assert r.pattern == PatternType.DIRECT
    assert captured["query"] == "aq"
    assert captured["skill_context"] == "sk"
    assert captured["classifier_timeout"] == 9.0
    assert captured["structured_max_retries"] == 1
    assert captured["llm"] is cfg["llm"]
    assert captured["tools"] == ["t1"]


@pytest.mark.asyncio
async def test_build_harness_context_returns_empty_when_disabled() -> None:
    assert await _build_harness_context_for_classify({"_harness_enabled": False}, is_frozen=False) == ""


@pytest.mark.asyncio
async def test_build_harness_context_reads_progress_tracker() -> None:
    tracker = MagicMock()
    tracker.get_classifier_context.return_value = "harness-body"

    ctx = await _build_harness_context_for_classify(
        {"_harness_enabled": True, "_progress_tracker": tracker},
        is_frozen=False,
    )
    assert ctx == "harness-body"


def test_coerce_unknown_pattern_noop_when_handler_exists() -> None:
    analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="", subtasks=[])
    out = _coerce_unknown_pattern_handler({}, analysis, registry=_HANDLERS)
    assert out.pattern == PatternType.DIRECT
