"""
Shared blackboard state — mutable dict of named slots.
Each slot starts as None and gets filled by a Knowledge Source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BlackboardState:
    """
    The shared knowledge space all KS workers read from and write to.

    Attributes:
        goal       : The original user query / objective.
        slots      : Named output slots. None = not yet filled.
        history    : Ordered log of (round, ks_id, output) entries.
        round      : Current execution round (0-indexed).
        filled     : Set of slot names that have been written.
        metadata   : Any extra context (tools used, tokens, etc.)
    """

    goal: str
    slots: dict[str, Any | None]
    history: list[dict] = field(default_factory=list)
    round: int = 0
    filled: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def write(self, slot: str, value: Any, ks_id: str) -> None:
        """Write a value to a slot and log it."""
        self.slots[slot] = value
        self.filled.add(slot)
        self.history.append(
            {
                "round": self.round,
                "ks_id": ks_id,
                "slot": slot,
                "output": value,
            }
        )

    def read(self, slot: str) -> Any | None:
        """Read a slot value. Returns None if not yet filled."""
        return self.slots.get(slot)

    def is_complete(self) -> bool:
        """True when all slots have been filled."""
        return all(v is not None for v in self.slots.values())

    def unfilled_slots(self) -> list[str]:
        """Return slot names not yet written."""
        return [k for k, v in self.slots.items() if v is None]

    def snapshot(self) -> str:
        """
        Compact text summary injected into each KS prompt.
        Shows all filled slots so each KS sees the full board.
        """
        lines = [f"GOAL: {self.goal}", ""]
        for slot, value in self.slots.items():
            status = "✅ FILLED" if value is not None else "⬜ EMPTY"
            lines.append(f"[{status}] {slot.upper()}:")
            if value:
                lines.append(f"  {str(value)[:300]}")
            else:
                lines.append("  (not yet filled)")
        return "\n".join(lines)
