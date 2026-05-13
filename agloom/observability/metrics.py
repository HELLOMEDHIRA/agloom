"""Per-session metrics derived from stored AGP events (SQLite, in-process)."""

from __future__ import annotations

from dataclasses import dataclass

from .store import SQLiteObservabilityStore

# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ToolMetric:
    tool: str
    call_count: int
    total_duration_ms: float
    error_count: int
    avg_duration_ms: float

@dataclass
class WorkerMetric:
    worker_id: str
    name: str
    pattern: str | None
    duration_ms: float | None
    status: str   # done | failed

@dataclass
class NodeMetric:
    node: str
    graph: str | None
    call_count: int
    total_duration_ms: float
    avg_duration_ms: float

@dataclass
class TurnMetric:
    turn_index: int
    user_message_preview: str
    input_tokens: int
    output_tokens: int
    thinking_steps: int
    tool_calls: int
    workers: int

@dataclass
class TimelinePoint:
    ts: str                # ISO-8601 wall-clock
    event_type: str
    label: str
    duration_ms: float | None
    seq: int

@dataclass
class SessionMetrics:
    session_id:          str
    total_events:        int
    total_turns:         int
    total_input_tokens:  int
    total_output_tokens: int
    session_duration_ms: int | None
    # Per-tool breakdown
    tools:               list[ToolMetric]
    # Worker summary
    workers:             list[WorkerMetric]
    # LangGraph node summary
    nodes:               list[NodeMetric]
    # Per-turn breakdown
    turns:               list[TurnMetric]
    # Chronological event timeline (for swimlane chart)
    timeline:            list[TimelinePoint]
    # Retry / error counts
    transient_errors:    int
    fatal_errors:        int
    hitl_gates:          int


# ── Aggregator ────────────────────────────────────────────────────────────────

class MetricsAggregator:
    """
    Builds ``SessionMetrics`` from stored AGP events.

    Usage::

        agg = MetricsAggregator(store)
        metrics = await agg.compute("s_abc123")
    """

    def __init__(self, store: SQLiteObservabilityStore) -> None:
        self._store = store

    async def compute(self, session_id: str) -> SessionMetrics:
        events = await self._store.get_events(session_id, limit=10_000)
        summary = await self._store.get_session(session_id)

        # ── Pass 1: raw aggregation ──────────────────────────────────────────

        tools: dict[str, dict] = {}            # tool_call_id → {...}
        tool_stats: dict[str, dict] = {}       # tool_name → aggregate
        workers: list[WorkerMetric] = []
        nodes: dict[str, dict] = {}            # node → aggregate
        turns: list[TurnMetric] = []
        timeline: list[TimelinePoint] = []

        current_turn: dict | None = None
        transient = 0
        fatal = 0
        hitl = 0
        turn_idx = 0

        for ev in events:
            p = ev.payload
            d = p.get("data") or {}

            # ── Timeline entry ───────────────────────────────────────────────
            label = _timeline_label(ev.event_type, d)
            if label:
                timeline.append(TimelinePoint(
                    ts=ev.ts, event_type=ev.event_type, label=label,
                    duration_ms=d.get("duration_ms") or d.get("elapsed_ms"),
                    seq=ev.seq,
                ))

            # ── Turn tracking ────────────────────────────────────────────────
            if ev.event_type == "message.user":
                current_turn = {
                    "idx": turn_idx,
                    "preview": str(d.get("content", ""))[:60],
                    "input_tokens": 0, "output_tokens": 0,
                    "thinking_steps": 0, "tool_calls": 0, "workers": 0,
                }
                turn_idx += 1

            elif ev.event_type == "message.assistant" and current_turn:
                turns.append(TurnMetric(
                    turn_index=current_turn["idx"],
                    user_message_preview=current_turn["preview"],
                    input_tokens=current_turn["input_tokens"],
                    output_tokens=current_turn["output_tokens"],
                    thinking_steps=current_turn["thinking_steps"],
                    tool_calls=current_turn["tool_calls"],
                    workers=current_turn["workers"],
                ))
                current_turn = None

            elif ev.event_type == "thinking.step" and current_turn:
                current_turn["thinking_steps"] += 1

            # ── Token accounting ─────────────────────────────────────────────
            elif ev.event_type == "metric.tokens":
                if current_turn:
                    current_turn["input_tokens"]  += d.get("input_tokens", 0)
                    current_turn["output_tokens"] += d.get("output_tokens", 0)

            # ── Tool calls ───────────────────────────────────────────────────
            elif ev.event_type == "tool.call":
                tid = d.get("tool_call_id", "")
                tools[tid] = {"tool": d.get("tool", ""), "start_ts": ev.ts}
                if current_turn:
                    current_turn["tool_calls"] += 1

            elif ev.event_type == "tool.result":
                tid = d.get("tool_call_id", "")
                tool_name = d.get("tool", "")
                dur = d.get("duration_ms") or 0.0
                err = bool(d.get("error"))
                if tool_name not in tool_stats:
                    tool_stats[tool_name] = {"count": 0, "total_ms": 0.0, "errors": 0}
                tool_stats[tool_name]["count"]    += 1
                tool_stats[tool_name]["total_ms"] += dur
                tool_stats[tool_name]["errors"]   += int(err)
                tools.pop(tid, None)

            # ── Workers ──────────────────────────────────────────────────────
            elif ev.event_type == "worker.spawned":
                if current_turn:
                    current_turn["workers"] += 1

            elif ev.event_type in ("worker.completed", "worker.failed"):
                wname = d.get("name")
                if wname is None or wname == "":
                    wname = d.get("worker_id") or ""
                workers.append(WorkerMetric(
                    worker_id=d.get("worker_id", ""),
                    name=str(wname),
                    pattern=d.get("pattern"),
                    duration_ms=d.get("duration_ms"),
                    status="done" if ev.event_type == "worker.completed" else "failed",
                ))

            # ── Graph nodes ──────────────────────────────────────────────────
            elif ev.event_type == "graph.node.enter":
                n = d.get("node", "")
                if n not in nodes:
                    nodes[n] = {"graph": d.get("graph"), "count": 0, "total_ms": 0.0}

            elif ev.event_type == "graph.node.exit":
                n = d.get("node", "")
                dur = d.get("duration_ms") or 0.0
                if n in nodes:
                    nodes[n]["count"]    += 1
                    nodes[n]["total_ms"] += dur

            # ── Errors / HITL ────────────────────────────────────────────────
            elif ev.event_type == "error.transient":
                transient += 1
            elif ev.event_type == "error.fatal":
                fatal += 1
            elif ev.event_type == "hitl.request":
                hitl += 1

        # ── Pass 2: build result objects ─────────────────────────────────────

        tool_metrics = [
            ToolMetric(
                tool=name,
                call_count=s["count"],
                total_duration_ms=s["total_ms"],
                error_count=s["errors"],
                avg_duration_ms=s["total_ms"] / s["count"] if s["count"] else 0.0,
            )
            for name, s in tool_stats.items()
        ]

        node_metrics = [
            NodeMetric(
                node=n,
                graph=info["graph"],
                call_count=info["count"],
                total_duration_ms=info["total_ms"],
                avg_duration_ms=info["total_ms"] / info["count"] if info["count"] else 0.0,
            )
            for n, info in nodes.items()
        ]

        return SessionMetrics(
            session_id=session_id,
            total_events=len(events),
            total_turns=summary.total_turns if summary else turn_idx,
            total_input_tokens=summary.input_tokens if summary else 0,
            total_output_tokens=summary.output_tokens if summary else 0,
            session_duration_ms=summary.duration_ms if summary else None,
            tools=tool_metrics,
            workers=workers,
            nodes=node_metrics,
            turns=turns,
            timeline=timeline,
            transient_errors=transient,
            fatal_errors=fatal,
            hitl_gates=hitl,
        )

    async def global_summary(self) -> dict:
        """Aggregate stats across all sessions — for the observability dashboard."""
        sessions = await self._store.list_sessions(limit=1000)
        total_sessions    = len(sessions)
        open_sessions     = sum(1 for s in sessions if s.status == "open")
        total_turns       = sum(s.total_turns for s in sessions)
        total_input_tok   = sum(s.input_tokens for s in sessions)
        total_output_tok  = sum(s.output_tokens for s in sessions)
        avg_duration      = (
            sum(s.duration_ms for s in sessions if s.duration_ms)
            / max(1, sum(1 for s in sessions if s.duration_ms))
        )
        return {
            "total_sessions":    total_sessions,
            "open_sessions":     open_sessions,
            "total_turns":       total_turns,
            "total_input_tokens":  total_input_tok,
            "total_output_tokens": total_output_tok,
            "avg_session_duration_ms": round(avg_duration),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _timeline_label(event_type: str, data: dict) -> str | None:
    """Return a human-readable label for swimlane rendering, or None to skip."""
    match event_type:
        case "session.opened":
            return "session start"
        case "session.closed":
            return f"session end ({data.get('reason', '?')})"
        case "pattern.classified":
            return f"pattern: {data.get('pattern', '?')}"
        case "tool.call":
            return f"tool: {data.get('tool', '?')}()"
        case "tool.result":
            return f"tool done: {data.get('tool', '?')}"
        case "worker.spawned":
            return f"worker: {data.get('name', '?')}"
        case "worker.completed":
            return f"worker done: {data.get('worker_id', '?')}"
        case "worker.failed":
            return f"worker failed: {data.get('worker_id', '?')}"
        case "graph.node.enter":
            return f"node enter: {data.get('node', '?')}"
        case "graph.node.exit":
            return f"node exit: {data.get('node', '?')}"
        case "hitl.request":
            return f"HITL: {data.get('kind', '?')}"
        case "checkpoint.saved":
            return "checkpoint saved"
        case "error.fatal":
            raw_msg = data.get("message", "?")
            msg = str(raw_msg)[:40]
            return f"fatal: {msg}"
        case "message.assistant":
            return "response"
        case _:
            return None
