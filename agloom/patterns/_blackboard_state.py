"""
Shared blackboard state — mutable dict of named slots.
Each slot starts as None and gets filled by a Knowledge Source on success.
Failed KS attempts are tracked separately so dependents unblock without
polluting synthesis or the success-only ``filled`` set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _value_marks_explicit_ks_failure(value: Any) -> bool:
    """True when worker output must not be stored as a successful slot value.

    KS workers sometimes return HTTP 200-style successes whose body is an explicit
    failure line (``FAILED: ...``). Treat those like :meth:`mark_failed` so
    :meth:`is_complete` / synthesis only see real content in ``filled``.
    """
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    first_line = text.split("\n", 1)[0].strip().lower()
    if first_line.startswith("failed:") or first_line.startswith("failure:"):
        return True
    if first_line.startswith("error:"):
        # Avoid treating benign lines like "error: completed successfully" as failures.
        tail = first_line[6:].strip()
        if not tail:
            return True
        success_markers = ("success", "completed", "ok", "done", "passed")
        return not any(m in tail for m in success_markers)
    return False


@dataclass
class BlackboardState:
    """
    The shared knowledge space all KS workers read from and write to.

    Attributes:
        goal       : The original user query / objective.
        slots      : Successful outputs only. None = not yet succeeded.
        failed     : slot -> error message for failed KS attempts.
        attempted  : Slots that have run (success or failure).
        history    : Ordered log of (round, ks_id, output) entries.
        round      : Current execution round (0-indexed).
        filled     : Set of slot names with successful content.
        metadata   : Any extra context (tools used, tokens, etc.)
    """

    goal: str
    slots: dict[str, Any | None]
    failed: dict[str, str] = field(default_factory=dict)
    attempted: set[str] = field(default_factory=set)
    history: list[dict] = field(default_factory=list)
    round: int = 0
    filled: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def write(self, slot: str, value: Any, ks_id: str) -> None:
        """Record a successful KS write."""
        if _value_marks_explicit_ks_failure(value):
            err = (
                str(value).strip()
                if value is not None and str(value).strip()
                else "empty or missing KS output"
            )
            self.mark_failed(slot, err, ks_id)
            return
        self.slots[slot] = value
        self.filled.add(slot)
        self.attempted.add(slot)
        self.failed.pop(slot, None)
        self.history.append(
            {
                "round": self.round,
                "ks_id": ks_id,
                "slot": slot,
                "status": "success",
                "output": value,
            }
        )

    def mark_failed(self, slot: str, error: str, ks_id: str) -> None:
        """Record a failed KS attempt without treating the slot as filled."""
        self.failed[slot] = error
        self.attempted.add(slot)
        self.history.append(
            {
                "round": self.round,
                "ks_id": ks_id,
                "slot": slot,
                "status": "failed",
                "error": error,
            }
        )

    def read(self, slot: str) -> Any | None:
        """Read a successful slot value. Returns None if not yet filled."""
        return self.slots.get(slot)

    def is_complete(self) -> bool:
        """True when every slot has been attempted (success or failure)."""
        return len(self.attempted) >= len(self.slots)

    def unfilled_slots(self) -> list[str]:
        """Return slot names without successful content."""
        return [k for k in self.slots if k not in self.filled]

    def snapshot(self) -> str:
        """
        Compact text summary injected into each KS prompt.
        Shows filled, failed, and empty slots so dependents see board state.
        """
        lines = [f"GOAL: {self.goal}", ""]
        for slot in self.slots:
            if slot in self.filled:
                status = "✅ FILLED"
                value = self.slots[slot]
            elif slot in self.failed:
                status = "❌ FAILED"
                value = f"FAILED: {self.failed[slot]}"
            else:
                status = "⬜ EMPTY"
                value = None
            lines.append(f"[{status}] {slot.upper()}:")
            if value is not None:
                lines.append(f"  {str(value)[:300]}")
            else:
                lines.append("  (not yet filled)")
        return "\n".join(lines)

    def synthesis_snapshot(self) -> str:
        """Board text for final synthesis — successful slots only."""
        lines = [f"GOAL: {self.goal}", ""]
        if not self.filled:
            lines.append("(no successful Knowledge Source outputs)")
            return "\n".join(lines)
        for slot in self.slots:
            if slot not in self.filled:
                continue
            value = self.slots[slot]
            lines.append(f"[{slot.upper()}]:")
            lines.append(f"  {str(value)[:2000]}")
        return "\n".join(lines)
