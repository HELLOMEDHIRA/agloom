"""Same-turn HITL dedupe: skip a second prompt only after Accept (Y) in the current user turn.

Session authorization is the **allowlist** (Allowlist / A), not coalescing. Coalescing only prevents
double approval before the agent finishes one turn (e.g. ``read_file`` with a smaller limit right
after you accepted a larger read on the same path). Each new user message clears coalesce state.
"""

from __future__ import annotations

import sys
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

# Long enough for one agent turn; cleared on each new user prompt (see ``reset_hitl_turn_coalescer``).
HITL_COALESCE_WINDOW_SEC = 600.0

# ``read_file`` scope: (canonical_path, offset, byte_limit, line_cap_or_none)
ReadFileScope = tuple[str, int, int, int | None]


class ToolHitlCoalescer(Protocol):
    """Optional skip of L2 HITL before a tool runs, after a recent human approval of a related call."""

    def should_skip_hitl(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        """Return True only when skipping the prompt is strictly equivalent to asking again."""

    def record_approval(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        """Record a grant so future calls may coalesce; implementations ignore unrelated tools."""


def _canonical_read_path(path: str) -> str:
    """Best-effort stable path key (symlinks, ``.``, case on case-insensitive FS)."""
    raw = path.strip()
    if not raw:
        return ""
    try:
        p = Path(raw)
        resolved = p.resolve(strict=False)
        if sys.platform == "win32":
            return str(resolved).lower()
        return str(resolved)
    except (OSError, RuntimeError, ValueError):
        if sys.platform == "win32":
            return Path(raw).as_posix().lower()
        return Path(raw).as_posix()


def parse_read_file_scope(tool_args: dict[str, Any]) -> ReadFileScope | None:
    """Normalize ``read_file`` args to a comparable scope (path, offset, byte limit, optional line_cap)."""
    raw = tool_args.get("path")
    if not isinstance(raw, str):
        return None
    path = _canonical_read_path(raw)
    if not path:
        return None
    try:
        off = int(tool_args.get("offset") or 0)
    except (TypeError, ValueError):
        off = 0
    try:
        lim = int(tool_args.get("limit") if tool_args.get("limit") is not None else 8000)
    except (TypeError, ValueError):
        lim = 8000
    line_cap_raw = tool_args.get("line_cap")
    line_cap: int | None
    if line_cap_raw is None:
        line_cap = None
    else:
        try:
            cap = int(line_cap_raw)
            line_cap = cap if cap > 0 else None
        except (TypeError, ValueError):
            line_cap = None
    return path, max(0, off), max(1, lim), line_cap


def read_file_scope_is_subset(new: ReadFileScope, approved: ReadFileScope) -> bool:
    """True when *new* reads the same file slice or less than *approved* (bytes + logical lines)."""
    n_path, n_off, n_lim, n_cap = new
    a_path, a_off, a_lim, a_cap = approved
    if n_path != a_path or n_off != a_off:
        return False
    if n_lim > a_lim:
        return False
    # Dropping line_cap can expose more logical lines from the same byte window — not a subset.
    if n_cap is None and a_cap is not None:
        return False
    if n_cap is not None and a_cap is not None and n_cap > a_cap:
        return False
    return True


class ReadFileSubsetCoalescer:
    """``read_file`` only: skip when a recent approval already covered this path/offset with ≥ bytes/lines."""

    __slots__ = ("_recent", "_window_sec")

    def __init__(self, *, window_sec: float = HITL_COALESCE_WINDOW_SEC) -> None:
        self._window_sec = window_sec
        self._recent: list[tuple[float, ReadFileScope]] = []

    def _prune(self, now: float) -> None:
        keep = self._window_sec
        self._recent = [t for t in self._recent if now - t[0] <= keep]

    def should_skip_hitl(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        if tool_name != "read_file":
            return False
        scope = parse_read_file_scope(tool_args)
        if scope is None:
            return False
        now = monotonic()
        self._prune(now)
        for ts, approved in self._recent:
            if now - ts > self._window_sec:
                continue
            if read_file_scope_is_subset(scope, approved):
                return True
        return False

    def record_approval(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        if tool_name != "read_file":
            return
        scope = parse_read_file_scope(tool_args)
        if scope is None:
            return
        now = monotonic()
        self._prune(now)
        self._recent.append((now, scope))

    def clear(self) -> None:
        self._recent.clear()


class CompositeToolHitlCoalescer:
    """Runs ordered coalescers; skip if any strategy approves skip (same user turn only)."""

    __slots__ = ("_strategies",)

    def __init__(self, strategies: list[ToolHitlCoalescer]) -> None:
        self._strategies = list(strategies)

    def should_skip_hitl(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        return any(s.should_skip_hitl(tool_name, tool_args) for s in self._strategies)

    def record_approval(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        for s in self._strategies:
            s.record_approval(tool_name, tool_args)

    def clear(self) -> None:
        for s in self._strategies:
            clear = getattr(s, "clear", None)
            if callable(clear):
                clear()


def build_default_hitl_coalescer() -> CompositeToolHitlCoalescer:
    """Per-turn coalescer: ``read_file`` subset dedupe after Accept (Y) within one user message."""
    return CompositeToolHitlCoalescer([ReadFileSubsetCoalescer()])


def reset_hitl_turn_coalescer(agent: Any) -> None:
    """Clear coalesce memory at the start of each user prompt (Accept does not carry over)."""
    coalescer: Any = None
    conf = getattr(agent, "config", None)
    if isinstance(conf, dict):
        coalescer = conf.get("_hitl_tool_coalescer")
    elif isinstance(agent, dict):
        coalescer = agent.get("_hitl_tool_coalescer")
    if coalescer is None:
        return
    clear = getattr(coalescer, "clear", None)
    if callable(clear):
        clear()
