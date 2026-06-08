"""REFLECTION goal synthesis when the classifier omits subtasks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agloom.models import (
    PatternType,
    QueryAnalysis,
    SubTask,
    WorkerResult,
    normalize_reflection_analysis,
)
from agloom.patterns.reflection import handle_reflection
from agloom.models import SignalType


def test_normalize_reflection_synthesizes_goal_from_query() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.REFLECTION,
        complexity=7,
        reasoning="needs polish",
        subtasks=[],
    )
    out = normalize_reflection_analysis(analysis, "  Draft the RCA report  ")
    assert len(out.subtasks) == 1
    assert out.subtasks[0].task == "Draft the RCA report"
    assert out.subtasks[0].worker_id == "goal"
    assert out.reasoning == "needs polish"


def test_normalize_reflection_preserves_existing_subtasks() -> None:
    st = SubTask(worker_id="worker_1", task="Write a literature review")
    analysis = QueryAnalysis(
        pattern=PatternType.REFLECTION,
        complexity=8,
        reasoning="ok",
        subtasks=[st],
    )
    out = normalize_reflection_analysis(analysis, "ignored")
    assert out.subtasks == [st]


def test_normalize_reflection_skips_non_reflection() -> None:
    analysis = QueryAnalysis(pattern=PatternType.REACT, complexity=5, reasoning="tools", subtasks=[])
    assert normalize_reflection_analysis(analysis, "query").subtasks == []


def test_normalize_reflection_empty_query_unchanged() -> None:
    analysis = QueryAnalysis(pattern=PatternType.REFLECTION, complexity=7, reasoning="x", subtasks=[])
    assert normalize_reflection_analysis(analysis, "   ").subtasks == []


@pytest.mark.asyncio
async def test_handle_reflection_runs_when_subtasks_synthesized() -> None:
    """Regression: REFLECTION + 0 subtasks must not hard-fail when query is non-empty."""
    analysis = QueryAnalysis(
        pattern=PatternType.REFLECTION,
        complexity=7,
        reasoning="rca draft",
        subtasks=[],
    )
    agent = {
        "name": "test",
        "llm": object(),
        "tools": [],
        "max_reflection_iterations": 1,
        "reflection_threshold": 10,
    }
    ok_result = WorkerResult(
        worker_id="generator_0",
        task="goal",
        output="Draft body",
        signal=SignalType.SUCCESS,
    )
    with patch(
        "agloom.patterns.reflection.run_workers_with_hitl",
        new_callable=AsyncMock,
    ) as mock_workers:
        mock_workers.side_effect = [
            ([ok_result], []),
            (
                [
                    WorkerResult(
                        worker_id="critic_0",
                        task="critique",
                        output="SCORE: 10\nPASSED: yes\nFEEDBACK: Great.",
                        signal=SignalType.SUCCESS,
                    )
                ],
                [],
            ),
        ]
        result = await handle_reflection(agent, "Produce RCA draft", analysis, config={"_steps": []})

    assert result.success is True
    assert "No reflection goal" not in (result.output or "")
    assert mock_workers.await_count == 2
