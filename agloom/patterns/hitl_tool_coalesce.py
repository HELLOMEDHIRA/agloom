"""Composable HITL coalescing: skip a redundant interrupt only when a tool-specific strategy says it is safe.

Human-in-the-loop is authorization, not caching. There is no generic “same JSON args” rule that is
correct across tools (writes, shell, network, etc. need explicit semantics). The scalable pattern is
a **registry of narrow strategies** (see ``CompositeToolHitlCoalescer``), each owned by one tool
family and covered by tests. Default behavior outside those strategies: always prompt.
"""

from __future__ import annotations

from typing import Any, Protocol


class ToolHitlCoalescer(Protocol):
    """Optional skip of L2 HITL before a tool runs, after a recent human approval of a related call."""

    def should_skip_hitl(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        """Return True only when skipping the prompt is strictly equivalent to asking again."""

    def record_approval(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        """Record a grant so future calls may coalesce; implementations ignore unrelated tools."""


class CompositeToolHitlCoalescer:
    """Runs ordered coalescers; skip if any strategy approves skip; every strategy sees ``record_approval``."""

    __slots__ = ("_strategies",)

    def __init__(self, strategies: list[ToolHitlCoalescer]) -> None:
        self._strategies = list(strategies)

    def should_skip_hitl(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        return any(s.should_skip_hitl(tool_name, tool_args) for s in self._strategies)

    def record_approval(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        for s in self._strategies:
            s.record_approval(tool_name, tool_args)
