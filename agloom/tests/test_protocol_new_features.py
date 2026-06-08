"""Tests for the newly implemented features:
- HITL server-side timeout enforcement
- command.feedback + command.snapshot.request parsing
- checkpoint.* / feedback.* / memory.* event round-trips
"""
from __future__ import annotations

import asyncio
import io
import json

import pytest

from agloom.protocol import (
    CheckpointRestored,
    CheckpointSaved,
    FeedbackScored,
    MemoryLtRecall,
    MemoryLtStore,
    MemorySessionTurnPopped,
    MemorySessionWrite,
    PlanPreview,
    event_adapter,
)
from agloom.protocol.commands import (
    CommandFeedback,
    CommandSnapshotRequest,
    command_adapter,
)
from agloom.protocol.emitter import SessionEmitter

# helpers


def _emitter() -> tuple[SessionEmitter, io.StringIO]:
    buf = io.StringIO()
    em = SessionEmitter(session="s_1", thread="t_1", writer=buf)
    return em, buf


def _lines(buf: io.StringIO) -> list[dict]:
    return [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]


# HITL server-side timeout


@pytest.mark.asyncio
async def test_hitl_timeout_auto_resolves():
    """When timeout_ms is set in the message payload, the bridge auto-resolves after the deadline."""
    from agloom.runtime.hitl import HITLBridge

    em, buf = _emitter()
    em.open()
    bridge = HITLBridge(em)

    # Attach a task (bridge routes HITL to per-task emitter)
    result_holder: list[str] = []

    async def _agent_turn() -> None:
        # message with timeout_ms=100ms — no frontend will respond, so the timeout fires
        ret = await bridge.callback(
            "tool_interrupt_before",
            {"tool_name": "run_shell", "detail": "Tool: run_shell", "timeout_ms": 100},
        )
        result_holder.append(ret)

    task = asyncio.create_task(_agent_turn())
    bridge.bind_task_emitter(task, em)
    await asyncio.wait_for(task, timeout=2.0)  # must complete well within 2s

    # Callback should have returned the safe default (abort path)
    assert len(result_holder) == 1
    assert result_holder[0] == "abort"

    # Wire should carry hitl.request + hitl.decided (timeout)
    lines = _lines(buf)
    types = [l["type"] for l in lines]
    assert "hitl.request" in types
    # The timeout decision is emitted as hitl.denied (decision=timeout)
    decisions = [l for l in lines if l["type"] in ("hitl.granted", "hitl.denied", "hitl.allowlisted")]
    assert len(decisions) == 1
    assert decisions[0]["data"]["decision"] == "timeout"


@pytest.mark.asyncio
async def test_hitl_no_timeout_waits_for_respond():
    """Without timeout_ms the bridge waits until respond() is called."""
    from agloom.runtime.hitl import HITLBridge

    em, buf = _emitter()
    em.open()
    bridge = HITLBridge(em)

    result_holder: list[str] = []

    async def _agent_turn() -> None:
        ret = await bridge.callback(
            "tool_interrupt_before",
            {"tool_name": "read_file", "detail": "Tool: read_file"},
        )
        result_holder.append(ret)

    task = asyncio.create_task(_agent_turn())
    bridge.bind_task_emitter(task, em)

    # Let the task start and emit hitl.request
    await asyncio.sleep(0.05)
    assert not task.done()

    # Now resolve it from the "frontend"
    lines_before = _lines(buf)
    requests = [l for l in lines_before if l["type"] == "hitl.request"]
    assert len(requests) == 1
    rid = requests[0]["data"]["request_id"]

    bridge.respond(rid, "accept")
    await asyncio.wait_for(task, timeout=1.0)
    assert result_holder[0] == "continue"


# CommandFeedback parsing


def test_command_feedback_parse():
    cmd = command_adapter.validate_python({
        "type": "command.feedback",
        "data": {"run_id": "run_1", "rating": "positive", "comment": "Great!", "correct": ""},
    })
    assert isinstance(cmd, CommandFeedback)
    assert cmd.data.run_id == "run_1"
    assert cmd.data.rating == "positive"
    assert cmd.data.comment == "Great!"


def test_command_feedback_defaults():
    cmd = command_adapter.validate_python({
        "type": "command.feedback",
        "data": {"run_id": "r", "rating": "negative"},
    })
    assert isinstance(cmd, CommandFeedback)
    assert cmd.data.comment == ""
    assert cmd.data.correct == ""
    assert cmd.data.metadata is None


def test_command_snapshot_request_parse():
    cmd = command_adapter.validate_python({
        "type": "command.snapshot.request",
        "data": {"thread": "t_1", "label": "my-snap"},
    })
    assert isinstance(cmd, CommandSnapshotRequest)
    assert cmd.data.thread == "t_1"
    assert cmd.data.label == "my-snap"


def test_command_snapshot_request_no_data():
    cmd = command_adapter.validate_python({"type": "command.snapshot.request"})
    assert isinstance(cmd, CommandSnapshotRequest)
    assert cmd.data.thread is None
    assert cmd.data.label is None


def test_emit_plan_preview():
    em, buf = _emitter()
    em.open()
    evt = em.emit_plan_preview(
        pattern="react",
        complexity=2,
        reasoning="User wants steps",
        steps=["1. Parse", "2. Act"],
    )
    assert isinstance(evt, PlanPreview)
    lines = _lines(buf)
    row = next(l for l in lines if l["type"] == "plan.preview")
    assert row["data"]["pattern"] == "react"
    assert row["data"]["complexity"] == 2
    assert row["data"]["steps"] == ["1. Parse", "2. Act"]


def test_plan_preview_event_round_trip():
    em, buf = _emitter()
    em.open()
    em.emit_plan_preview(pattern="sequential", steps=["a"])
    raw = next(l for l in _lines(buf) if l["type"] == "plan.preview")
    parsed = event_adapter.validate_python(raw)
    assert isinstance(parsed, PlanPreview)
    assert parsed.data.pattern == "sequential"


# checkpoint.* events


def test_emit_checkpoint_saved():
    em, buf = _emitter()
    em.open()
    evt = em.emit_checkpoint_saved(thread="t_1", run_id="run_abc", label="my-label")
    assert isinstance(evt, CheckpointSaved)
    lines = _lines(buf)
    ckpt = next(l for l in lines if l["type"] == "checkpoint.saved")
    assert ckpt["data"]["thread"] == "t_1"
    assert ckpt["data"]["run_id"] == "run_abc"
    assert ckpt["data"]["label"] == "my-label"


def test_emit_checkpoint_restored():
    em, buf = _emitter()
    em.open()
    evt = em.emit_checkpoint_restored(thread="t_1", resumed_from_run_id="run_old")
    assert isinstance(evt, CheckpointRestored)
    lines = _lines(buf)
    ckpt = next(l for l in lines if l["type"] == "checkpoint.restored")
    assert ckpt["data"]["resumed_from_run_id"] == "run_old"


def test_checkpoint_event_round_trip():
    em, buf = _emitter()
    em.open()
    em.emit_checkpoint_saved(thread="t_1", run_id="r_1")
    em.emit_checkpoint_restored(thread="t_1")
    for raw in _lines(buf):
        parsed = event_adapter.validate_python(raw)
        assert parsed.type in ("session.opened", "checkpoint.saved", "checkpoint.restored")


# feedback.* events


def test_emit_feedback_scored():
    em, buf = _emitter()
    em.open()
    evt = em.emit_feedback_scored(run_id="r_1", rating="positive", comment="Nice!", correct="yes")
    assert isinstance(evt, FeedbackScored)
    lines = _lines(buf)
    fb = next(l for l in lines if l["type"] == "feedback.scored")
    assert fb["data"]["run_id"] == "r_1"
    assert fb["data"]["rating"] == "positive"
    assert fb["data"]["comment"] == "Nice!"


def test_feedback_event_round_trip():
    em, buf = _emitter()
    em.open()
    em.emit_feedback_scored(run_id="r_1", rating="negative")
    raw = next(l for l in _lines(buf) if l["type"] == "feedback.scored")
    parsed = event_adapter.validate_python(raw)
    assert isinstance(parsed, FeedbackScored)
    assert parsed.data.rating == "negative"


# memory.* events


def test_emit_memory_session_write():
    em, buf = _emitter()
    em.open()
    evt = em.emit_memory_session_write(
        thread="t_1", run_id="r_1", query_preview="hello", output_preview="world", turn_count=3,
    )
    assert isinstance(evt, MemorySessionWrite)
    lines = _lines(buf)
    mem = next(l for l in lines if l["type"] == "memory.session.write")
    assert mem["data"]["turn_count"] == 3


def test_emit_memory_session_turn_popped():
    em, buf = _emitter()
    em.open()
    evt = em.emit_memory_session_turn_popped(thread="t_1", remaining_turns=0)
    assert isinstance(evt, MemorySessionTurnPopped)
    lines = _lines(buf)
    raw = next(l for l in lines if l["type"] == "memory.session.turn_popped")
    parsed = event_adapter.validate_python(raw)
    assert isinstance(parsed, MemorySessionTurnPopped)
    assert parsed.data.remaining_turns == 0


def test_emit_memory_lt_recall():
    em, buf = _emitter()
    em.open()
    evt = em.emit_memory_lt_recall(namespace="user/def", query_preview="q", hits=2, injected_chars=300)
    assert isinstance(evt, MemoryLtRecall)
    lines = _lines(buf)
    mem = next(l for l in lines if l["type"] == "memory.lt.recall")
    assert mem["data"]["hits"] == 2
    assert mem["data"]["injected_chars"] == 300


def test_emit_memory_lt_store():
    em, buf = _emitter()
    em.open()
    evt = em.emit_memory_lt_store(namespace="user/def", key="project_goal", content_preview="Build AI...")
    assert isinstance(evt, MemoryLtStore)
    lines = _lines(buf)
    mem = next(l for l in lines if l["type"] == "memory.lt.store")
    assert mem["data"]["key"] == "project_goal"


def test_all_memory_events_round_trip():
    em, buf = _emitter()
    em.open()
    em.emit_memory_lt_recall(hits=0)
    em.emit_memory_session_write(thread="t_1")
    em.emit_memory_lt_store()
    for raw in _lines(buf):
        parsed = event_adapter.validate_python(raw)
        assert parsed.type in (
            "session.opened",
            "memory.lt.recall",
            "memory.session.write",
            "memory.lt.store",
        )


# new commands in the full Event union


def test_feedback_command_json_round_trip():
    raw = {"type": "command.feedback", "data": {"run_id": "r", "rating": "positive"}}
    cmd = command_adapter.validate_python(raw)
    dumped = json.loads(cmd.model_dump_json())
    assert dumped["type"] == "command.feedback"


def test_snapshot_command_json_round_trip():
    raw = {"type": "command.snapshot.request", "data": {"label": "snap-1"}}
    cmd = command_adapter.validate_python(raw)
    dumped = json.loads(cmd.model_dump_json())
    assert dumped["type"] == "command.snapshot.request"
