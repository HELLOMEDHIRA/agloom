"""Checkpoint channel_versions monotonicity and ``analysis`` persistence in channel_values."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from agloom.models import ExecutionResult, PatternType, QueryAnalysis
from agloom.unified_agent import _analysis_from_checkpoint_values, _save_checkpoint


@pytest.mark.asyncio
async def test_save_checkpoint_versions_preserve_history() -> None:
    """Without per-save version bumps, MemorySaver overwrites blobs — old checkpoints show new text."""
    cp = MemorySaver()
    thread = "thread-a"
    r1 = ExecutionResult(
        pattern_used=PatternType.REACT,
        query="ignored",
        output="first-output",
        run_id="chk-first",
    )
    r2 = ExecutionResult(
        pattern_used=PatternType.REACT,
        query="ignored",
        output="second-output",
        run_id="chk-second",
    )
    await _save_checkpoint(cp, thread, r1, "q1")
    await _save_checkpoint(cp, thread, r2, "q2")

    t_first = await cp.aget_tuple(
        {
            "configurable": {
                "thread_id": thread,
                "checkpoint_ns": "",
                "checkpoint_id": "chk-first",
            }
        }
    )
    t_second = await cp.aget_tuple(
        {
            "configurable": {
                "thread_id": thread,
                "checkpoint_ns": "",
                "checkpoint_id": "chk-second",
            }
        }
    )
    assert t_first is not None and t_second is not None
    assert t_first.checkpoint["channel_values"]["output"] == "first-output"
    assert t_second.checkpoint["channel_values"]["output"] == "second-output"

    cv1 = t_first.checkpoint["channel_versions"]
    cv2 = t_second.checkpoint["channel_versions"]
    assert cv1["output"] != cv2["output"], "expected version bump per channel per save"


@pytest.mark.asyncio
async def test_save_checkpoint_persists_analysis() -> None:
    cp = MemorySaver()
    thread = "thread-analysis"
    analysis = QueryAnalysis(
        pattern=PatternType.SWARM,
        complexity=7,
        reasoning="multi-agent",
        subtasks=[],
    )
    result = ExecutionResult(
        pattern_used=PatternType.SWARM,
        query="plan swarm",
        output="done",
        run_id="chk-analysis",
        analysis=analysis,
    )
    await _save_checkpoint(cp, thread, result, "plan swarm")

    t = await cp.aget_tuple(
        {
            "configurable": {
                "thread_id": thread,
                "checkpoint_ns": "",
                "checkpoint_id": "chk-analysis",
            }
        }
    )
    assert t is not None
    cv = t.checkpoint["channel_values"]
    restored = _analysis_from_checkpoint_values(cv)
    assert restored is not None
    assert restored.pattern == PatternType.SWARM
    assert restored.complexity == 7
