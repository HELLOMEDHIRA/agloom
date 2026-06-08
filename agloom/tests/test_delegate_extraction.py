"""Delegate name extraction from classifier reasoning."""

from __future__ import annotations

from agloom.delegation import HandoffTarget
from agloom.models import PatternType, QueryAnalysis
from agloom.unified_agent import _extract_delegate_from_analysis


def test_delegate_requires_word_boundary() -> None:
    targets = [HandoffTarget(object(), name="rag")]
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=5,
        reasoning="The average score improved after barrage testing.",
        subtasks=[],
    )
    assert _extract_delegate_from_analysis(analysis, targets) is None

    analysis2 = analysis.model_copy(update={"reasoning": "Route this to the rag worker."})
    assert _extract_delegate_from_analysis(analysis2, targets) == "rag"
