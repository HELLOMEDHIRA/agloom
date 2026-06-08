"""HITLBridge — wire translation, future-based pending registry, decision routing."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

from agloom.hitl_contract import HITLEvent
from agloom.protocol import (
    HITLAllowlisted,
    HITLDenied,
    HITLGranted,
    HITLRequest,
    SessionEmitter,
    event_adapter,
)
from agloom.runtime.hitl import HITLBridge


def _read_events(buf: io.StringIO) -> list:
    buf.seek(0)
    return [event_adapter.validate_python(json.loads(line)) for line in buf if line.strip()]


def _make_bridge() -> tuple[HITLBridge, io.StringIO]:
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    return HITLBridge(em), buf


# per-event-type kind mapping


@pytest.mark.asyncio
async def test_tool_interrupt_before_emits_tool_approval_request() -> None:
    bridge, buf = _make_bridge()

    async def caller() -> str:
        return await bridge.callback(
            HITLEvent.TOOL_INTERRUPT_BEFORE,
            {
                "tool_name": "read_file",
                "tool_call_id": "tc_42",
                "args": {"path": "x.py"},
                "agent_name": "ag",
                "detail": "Tool: read_file",
            },
        )

    task = asyncio.create_task(caller())
    await asyncio.sleep(0)  # let request hit the wire
    events = _read_events(buf)
    req = next(e for e in events if isinstance(e, HITLRequest))
    assert req.data.kind == "tool_approval"
    assert req.data.tool == "read_file"
    assert req.data.tool_call_id == "tc_42"
    assert req.data.args == {"path": "x.py"}
    assert req.data.options == ["accept", "reject", "allowlist"]
    assert req.data.default == "reject"

    # Resolve and verify return value + outcome event.
    assert bridge.respond(req.data.request_id, "accept") is True
    result = await task
    assert result == "continue"
    final_events = _read_events(buf)
    granted = [e for e in final_events if isinstance(e, HITLGranted)]
    assert len(granted) == 1
    assert granted[0].data.decision == "accept"


@pytest.mark.asyncio
async def test_tool_interrupt_reject_returns_abort_and_emits_denied() -> None:
    bridge, buf = _make_bridge()
    task = asyncio.create_task(
        bridge.callback(HITLEvent.TOOL_INTERRUPT_BEFORE, {"tool_name": "run_shell"})
    )
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    bridge.respond(req.data.request_id, "reject")
    assert await task == "abort"
    assert any(isinstance(e, HITLDenied) for e in _read_events(buf))


@pytest.mark.asyncio
async def test_tool_interrupt_allowlist_returns_continue_and_emits_allowlisted() -> None:
    bridge, buf = _make_bridge()
    task = asyncio.create_task(
        bridge.callback(HITLEvent.TOOL_INTERRUPT_BEFORE, {"tool_name": "run_shell"})
    )
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    bridge.respond(req.data.request_id, "allowlist")
    assert await task == "continue"
    final = _read_events(buf)
    assert any(isinstance(e, HITLAllowlisted) for e in final)


@pytest.mark.asyncio
async def test_clarification_returns_user_text_answer() -> None:
    bridge, buf = _make_bridge()
    task = asyncio.create_task(
        bridge.callback(HITLEvent.CLARIFICATION_REQUEST, {"question": "OTP code?", "worker_id": "w1"})
    )
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    assert req.data.kind == "clarification"
    assert req.data.options == []  # free-text, no discrete choices
    bridge.respond(req.data.request_id, "accept", text="123456")
    assert await task == "123456"


@pytest.mark.asyncio
async def test_react_recovery_retry_returns_retry() -> None:
    """``REACT_TOOL_USE_FAILED`` → retry-or-stop, not the 3-way card."""
    bridge, buf = _make_bridge()
    task = asyncio.create_task(bridge.callback(HITLEvent.REACT_TOOL_USE_FAILED, "provider rejected"))
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    assert req.data.kind == "react_recovery"
    assert req.data.options == ["retry", "stop"]
    bridge.respond(req.data.request_id, "retry")
    assert await task == "retry"


@pytest.mark.asyncio
async def test_react_recovery_stop_returns_abort() -> None:
    bridge, buf = _make_bridge()
    task = asyncio.create_task(bridge.callback(HITLEvent.REACT_TOOL_USE_FAILED, "x"))
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    bridge.respond(req.data.request_id, "stop")
    assert await task == "abort"


@pytest.mark.asyncio
async def test_pattern_interrupt_emits_pattern_approval() -> None:
    bridge, buf = _make_bridge()
    task = asyncio.create_task(bridge.callback(HITLEvent.PATTERN_INTERRUPT, "[REACT]\nQuery: x"))
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    assert req.data.kind == "pattern_approval"
    bridge.respond(req.data.request_id, "accept")
    assert await task == "continue"


# lifecycle / robustness


def test_respond_returns_false_for_unknown_request_id() -> None:
    bridge, _ = _make_bridge()
    assert bridge.respond("hr_does_not_exist", "accept") is False


@pytest.mark.asyncio
async def test_garbled_decision_falls_back_to_reject() -> None:
    """A garbled inbound decision token must NOT auto-approve — it normalizes to ``reject``."""
    bridge, buf = _make_bridge()
    task = asyncio.create_task(bridge.callback(HITLEvent.TOOL_INTERRUPT_BEFORE, {"tool_name": "x"}))
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    bridge.respond(req.data.request_id, "lgtm-or-something")  # not in _VALID_DECISIONS
    assert await task == "abort"
    # Outcome event should still be emitted, with the normalized "reject"
    denied = [e for e in _read_events(buf) if isinstance(e, HITLDenied)]
    assert denied and denied[0].data.decision == "reject"


@pytest.mark.asyncio
async def test_double_respond_is_noop() -> None:
    """A second response to the same request_id must not raise or re-resolve."""
    bridge, buf = _make_bridge()
    task = asyncio.create_task(bridge.callback(HITLEvent.TOOL_INTERRUPT_BEFORE, {"tool_name": "x"}))
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    assert bridge.respond(req.data.request_id, "accept") is True
    await task
    # Future already resolved; second respond returns False.
    assert bridge.respond(req.data.request_id, "reject") is False


@pytest.mark.asyncio
async def test_cancel_all_resolves_pending_with_cancelled() -> None:
    """``cancel_all`` lets shutdowns unblock awaiting agents promptly."""
    bridge, buf = _make_bridge()
    task = asyncio.create_task(bridge.callback(HITLEvent.TOOL_INTERRUPT_BEFORE, {"tool_name": "x"}))
    await asyncio.sleep(0)
    assert bridge.pending_count == 1
    n = bridge.cancel_all()
    assert n == 1
    # Callback returns abort because cancelled normalizes to abort
    assert await task == "abort"
    assert bridge.pending_count == 0


@pytest.mark.asyncio
async def test_pending_count_tracks_active_requests() -> None:
    bridge, buf = _make_bridge()
    t1 = asyncio.create_task(bridge.callback(HITLEvent.TOOL_INTERRUPT_BEFORE, {"tool_name": "a"}))
    t2 = asyncio.create_task(bridge.callback(HITLEvent.TOOL_INTERRUPT_BEFORE, {"tool_name": "b"}))
    await asyncio.sleep(0)
    assert bridge.pending_count == 2
    reqs = [e for e in _read_events(buf) if isinstance(e, HITLRequest)]
    bridge.respond(reqs[0].data.request_id, "accept")
    bridge.respond(reqs[1].data.request_id, "reject")
    await asyncio.gather(t1, t2)
    assert bridge.pending_count == 0


@pytest.mark.asyncio
async def test_string_message_extracts_tool_name_from_detail() -> None:
    """Legacy callers pass a string with ``Tool: <name>`` — bridge should parse it out."""
    bridge, buf = _make_bridge()
    task = asyncio.create_task(
        bridge.callback(HITLEvent.TOOL_INTERRUPT_BEFORE, "Tool: search_web\nArgs: {q:cats}")
    )
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    assert req.data.tool == "search_web"
    assert req.data.detail == "Tool: search_web\nArgs: {q:cats}"
    bridge.respond(req.data.request_id, "accept")
    await task


@pytest.mark.asyncio
async def test_allowlist_decision_persists_named_tool(tmp_path: Path) -> None:
    from agloom.runtime.hitl_allowlist import load_tool_allowlist

    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    path = tmp_path / "allow.json"
    shared: set[str] = set()
    bridge = HITLBridge(em, tool_allowlist=shared, allowlist_persist_path=path)
    task = asyncio.create_task(
        bridge.callback(
            HITLEvent.TOOL_INTERRUPT_BEFORE,
            {"tool_name": "execute", "agent_name": "g", "args": {}},
        )
    )
    await asyncio.sleep(0)
    req = next(e for e in _read_events(buf) if isinstance(e, HITLRequest))
    bridge.respond(req.data.request_id, "allowlist")
    await task
    assert "execute" in shared
    assert "execute" in load_tool_allowlist(path)
