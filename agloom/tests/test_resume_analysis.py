"""Checkpoint / resume helpers must round-trip ``QueryAnalysis`` without re-classify."""

from __future__ import annotations

from agloom.models import PatternType, QueryAnalysis
from agloom.unified_agent import (
    _analysis_from_checkpointer_tuple,
    _analysis_from_checkpoint_values,
)


def test_analysis_from_checkpoint_values_roundtrip() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.HYBRID_DAG,
        complexity=5,
        reasoning="dag",
        subtasks=[],
    )
    cv = {"analysis": analysis.model_dump(), "query": "build pipeline"}
    restored = _analysis_from_checkpoint_values(cv)
    assert restored is not None
    assert restored.pattern == PatternType.HYBRID_DAG


def test_analysis_from_checkpointer_tuple_reads_nested_checkpoint() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.REFLECTION,
        complexity=4,
        reasoning="reflect",
        subtasks=[],
    )

    class _Tuple:
        checkpoint = {
            "channel_values": {
                "analysis": analysis.model_dump(),
            }
        }

    restored = _analysis_from_checkpointer_tuple(_Tuple())
    assert restored is not None
    assert restored.pattern == PatternType.REFLECTION
