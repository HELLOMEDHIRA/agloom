"""Tests for the LangGraph classify node (classifier params + skill context)."""

from __future__ import annotations

import pytest

from agloom.graph import _make_classify_node
from agloom.models import PatternType, QueryAnalysis


@pytest.mark.asyncio
async def test_graph_classify_forwards_classifier_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_execute(
        cfg: dict,
        *,
        augmented_query: str,
        skill_context: str,
    ) -> QueryAnalysis:
        captured["cfg"] = cfg
        captured["augmented_query"] = augmented_query
        captured["skill_context"] = skill_context
        return QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="ok", subtasks=[])

    monkeypatch.setattr("agloom.unified_agent._execute_analyze_query", fake_execute)

    agent = {
        "name": "graph-test",
        "llm": object(),
        "tools": ["t1"],
        "classifier_timeout": 12.0,
        "structured_max_retries": 3,
        "fallback_pattern": PatternType.REACT,
    }
    node = _make_classify_node(agent)
    out = await node({"query": "hello", "analysis": None, "result": None}, {})

    assert captured["augmented_query"] == "hello"
    assert captured["skill_context"] == ""
    assert captured["cfg"] is agent
    assert out["analysis"].pattern == PatternType.DIRECT


@pytest.mark.asyncio
async def test_graph_classify_injects_skill_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_execute(
        cfg: dict,
        *,
        augmented_query: str,
        skill_context: str,
    ) -> QueryAnalysis:
        captured["skill_context"] = skill_context
        return QueryAnalysis(pattern=PatternType.REACT, complexity=2, reasoning="ok", subtasks=[])

    class _Injector:
        async def get_context(self, query: str) -> str:
            return f"skills-for-{query}"

    monkeypatch.setattr("agloom.unified_agent._execute_analyze_query", fake_execute)

    agent = {"name": "graph-test", "llm": object(), "skill_injector": _Injector()}
    node = _make_classify_node(agent)
    out = await node({"query": "deploy", "analysis": None, "result": None}, {})

    assert captured["skill_context"] == "skills-for-deploy"
    assert out["analysis"].pattern == PatternType.REACT


@pytest.mark.asyncio
async def test_graph_classify_skill_injector_failure_proceeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def fake_execute(
        cfg: dict,
        *,
        augmented_query: str,
        skill_context: str,
    ) -> QueryAnalysis:
        captured["skill_context"] = skill_context
        return QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="ok", subtasks=[])

    class _BrokenInjector:
        async def get_context(self, query: str) -> str:
            raise RuntimeError("injector down")

    monkeypatch.setattr("agloom.unified_agent._execute_analyze_query", fake_execute)

    agent = {"name": "graph-test", "llm": object(), "skill_injector": _BrokenInjector()}
    node = _make_classify_node(agent)
    await node({"query": "q", "analysis": None, "result": None}, {})

    assert captured["skill_context"] == ""


@pytest.mark.asyncio
async def test_graph_classify_noop_when_preclassified(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_execute(*_a: object, **_k: object) -> QueryAnalysis:
        raise AssertionError("classify should not run when analysis is preset")

    monkeypatch.setattr("agloom.unified_agent._execute_analyze_query", fail_execute)

    pre = QueryAnalysis(pattern=PatternType.SUPERVISOR, complexity=5, reasoning="preset", subtasks=[])
    agent = {"name": "graph-test", "llm": object()}
    node = _make_classify_node(agent)
    out = await node({"query": "hello", "analysis": pre, "result": None}, {})

    assert out == {}
