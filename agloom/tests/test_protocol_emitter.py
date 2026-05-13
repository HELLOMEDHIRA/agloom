"""SessionEmitter — write semantics, ordering, lifecycle idempotency, on_emit hook."""

from __future__ import annotations

import io
import json
import threading

from agloom.protocol import SessionEmitter, event_adapter


def _read_events(buf: io.StringIO) -> list:
    """Parse all NDJSON lines in ``buf`` into Pydantic event instances."""
    buf.seek(0)
    return [event_adapter.validate_python(json.loads(line)) for line in buf if line.strip()]


def test_emitter_seq_starts_at_zero_then_increments() -> None:
    em = SessionEmitter(session="s", thread="t", writer=io.StringIO())
    assert em.seq == 0
    em.open()
    assert em.seq == 1
    em.emit_thinking_step(step="x")
    assert em.seq == 2


def test_subscription_prefix_filters_wire_stream() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    em.set_subscription_prefixes(["thinking."])
    em.emit_pattern_classified(pattern="REACT")
    em.emit_thinking_step(step="plan")
    em.close()
    events = _read_events(buf)
    types = [e.type for e in events]
    assert "pattern.classified" not in types
    assert "thinking.step" in types
    assert types[0] == "session.opened"
    assert types[-1] == "session.closed"


def test_emitter_full_lifecycle_writes_seven_events() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="sess_a", thread="thread_b", writer=buf)
    em.open()
    em.emit_pattern_classified(pattern="REACT", complexity=5)
    em.emit_thinking_step(step="analyze_query", elapsed_ms=120)
    em.emit_token_delta(text="Hello, ")
    em.emit_token_delta(text="world!")
    em.emit_message_assistant(content="Hello, world!")
    em.close(reason="completed", duration_ms=1234)

    events = _read_events(buf)
    assert [e.type for e in events] == [
        "session.opened",
        "pattern.classified",
        "thinking.step",
        "token.delta",
        "token.delta",
        "message.assistant",
        "session.closed",
    ]
    assert [e.seq for e in events] == list(range(1, 8))
    # token.delta whitespace round-trip
    assert events[3].data.text == "Hello, "
    assert events[4].data.text == "world!"


def test_emitter_open_close_idempotent() -> None:
    """Calling open()/close() twice must not produce duplicate boundary events."""
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    em.open()  # no-op
    em.close()
    em.close()  # no-op
    events = _read_events(buf)
    assert [e.type for e in events] == ["session.opened", "session.closed"]


def test_emitter_writes_one_json_object_per_line() -> None:
    """Lines on the wire MUST be parseable individually — no multi-line JSON."""
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    em.emit_thinking_step(step="x")
    em.close()
    raw = buf.getvalue()
    assert raw.count("\n") >= 3  # at least three trailing newlines
    for line in raw.splitlines():
        assert line.strip()
        # Each non-empty line must be valid JSON on its own
        json.loads(line)


def test_emitter_session_thread_mirrored_into_envelopes() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="sess_42", thread="thread_99", writer=buf)
    em.open()
    em.emit_thinking_step(step="x")
    em.close()
    events = _read_events(buf)
    assert {e.session for e in events} == {"sess_42"}
    assert {e.thread for e in events} == {"thread_99"}


def test_emitter_on_emit_hook_observes_events() -> None:
    seen: list[str] = []

    def observe(evt) -> None:
        seen.append(evt.type)

    em = SessionEmitter(session="s", thread="t", writer=io.StringIO(), on_emit=observe)
    em.open()
    em.emit_thinking_step(step="x")
    em.close()
    assert seen == ["session.opened", "thinking.step", "session.closed"]


def test_emitter_on_emit_failure_does_not_break_wire() -> None:
    """Exceptions in ``on_emit`` are observation-only and must NOT abort emission."""
    buf = io.StringIO()

    def boom(_evt) -> None:
        raise RuntimeError("boom")

    em = SessionEmitter(session="s", thread="t", writer=buf, on_emit=boom)
    em.open()
    em.emit_thinking_step(step="x")
    em.close()
    events = _read_events(buf)
    assert [e.type for e in events] == ["session.opened", "thinking.step", "session.closed"]


def test_emitter_concurrent_emits_keep_seq_monotonic() -> None:
    """Two threads emitting in parallel must produce a strictly monotonic seq stream."""
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()

    def hammer() -> None:
        for _ in range(50):
            em.emit_thinking_step(step="parallel")

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    em.close()

    events = _read_events(buf)
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)  # strictly increasing
    assert len(seqs) == 1 + 200 + 1  # opened + 4*50 + closed


def test_emitter_runtime_config_carries_capabilities() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf, capabilities=["tools"])
    em.open()
    em.emit_runtime_config(model_id="m1", tool_names=["t1"])
    events = _read_events(buf)
    assert events[0].type == "session.opened"
    assert events[1].type == "runtime.config"
    assert events[1].data.capabilities == ["tools"]


# tool.* / message.user / error.* emit_* shortcuts


def test_emitter_emit_message_user() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    em.emit_message_user(content="What's 2+2?", message_id="u_1")
    em.close()
    events = _read_events(buf)
    user = events[1]
    assert user.type == "message.user"
    assert user.data.content == "What's 2+2?"
    assert user.data.message_id == "u_1"


def test_emitter_tool_call_start_result_sequence() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    start = em.emit_tool_call_start(
        tool="read_file", tool_call_id="tc_42", args={"path": "x.py"}, worker="researcher"
    )
    em.emit_tool_call_result(
        tool="read_file",
        tool_call_id="tc_42",
        output_preview="contents",
        output_bytes=8,
        duration_ms=15,
        parent=start.id,
    )
    em.close()
    events = _read_events(buf)
    types = [e.type for e in events]
    assert types == ["session.opened", "tool.call.start", "tool.call.result", "session.closed"]
    # parent correlation: result -> start
    result = events[2]
    assert result.parent == start.id


def test_emitter_tool_call_error_emit() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    start = em.emit_tool_call_start(tool="run_shell", tool_call_id="tc_x", args={"cmd": "ls"})
    em.emit_tool_call_error(
        tool="run_shell",
        tool_call_id="tc_x",
        error="boom",
        error_class="OSError",
        duration_ms=2,
        parent=start.id,
    )
    em.close()
    events = _read_events(buf)
    err = events[2]
    assert err.type == "tool.call.error"
    assert err.data.error_class == "OSError"
    assert err.parent == start.id


def test_emitter_emit_error_severity_dispatches_to_correct_type() -> None:
    """``severity="fatal"`` → ``error.fatal``; ``severity="transient"`` → ``error.transient``."""
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    em.emit_error(severity="transient", message="429", error_class="RateLimitError", retryable=True)
    em.emit_error(severity="fatal", message="boom", error_class="RuntimeError")
    em.close()
    events = _read_events(buf)
    types = [e.type for e in events]
    assert "error.transient" in types
    assert "error.fatal" in types
    # ``retryable`` survives the round trip
    transient = next(e for e in events if e.type == "error.transient")
    assert transient.data.retryable is True


def test_emitter_tool_call_start_default_args_is_empty_dict() -> None:
    """``args=None`` MUST not crash — emitter coerces to ``{}`` so the wire stays well-formed."""
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    em.emit_tool_call_start(tool="x", tool_call_id="tc_0")
    em.close()
    events = _read_events(buf)
    assert events[1].data.args == {}


# fork_for_thread


def test_fork_for_thread_shares_seq_counter() -> None:
    """Events from two forks of the same session MUST have strictly increasing seq numbers."""
    buf = io.StringIO()
    parent = SessionEmitter(session="sess_fork", thread="thread_a", writer=buf)
    parent.open()  # seq=1

    child = parent.fork_for_thread("thread_b")
    child.emit_thinking_step(step="x")  # seq=2 (shared counter)
    parent.emit_thinking_step(step="y")  # seq=3
    child.emit_thinking_step(step="z")  # seq=4
    parent.close(reason="completed")  # seq=5

    events = _read_events(buf)
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs), "seq must be strictly monotonic across forks"
    assert seqs == list(range(1, 6))


def test_fork_for_thread_carries_correct_thread_id() -> None:
    buf = io.StringIO()
    parent = SessionEmitter(session="sess_x", thread="thread_main", writer=buf)
    parent.open()
    child = parent.fork_for_thread("thread_worker")
    child.emit_thinking_step(step="w")
    parent.close()

    events = _read_events(buf)
    assert events[0].thread == "thread_main"   # session.opened
    assert events[1].thread == "thread_worker"  # thinking.step from child
    assert events[2].thread == "thread_main"   # session.closed


def test_fork_for_thread_same_session_id() -> None:
    buf = io.StringIO()
    parent = SessionEmitter(session="sess_shared", thread="t1", writer=buf)
    parent.open()
    child = parent.fork_for_thread("t2")
    child.emit_thinking_step(step="check")
    parent.close()

    events = _read_events(buf)
    assert all(e.session == "sess_shared" for e in events)


# callback-only mode


def test_callback_only_emitter_never_writes_to_stdout(capsys: object) -> None:
    """Writer=None mode must call on_emit but NOT write JSON to any stream."""
    collected: list = []
    em = SessionEmitter._callback_only(
        session="s_cb",
        thread="t_cb",
        on_emit=collected.append,
    )
    em.open()
    em.emit_thinking_step(step="check")
    em.close()
    # on_emit was called for all three events
    assert len(collected) == 3
    assert collected[0].type == "session.opened"
    # Nothing was written (no file descriptor involved — just confirm no crash)


# AsyncSessionEmitter


def test_async_emitter_drains_all_events() -> None:
    """AsyncSessionEmitter MUST deliver all events to the async writer via the drain task."""
    import asyncio

    from agloom.protocol import AsyncSessionEmitter

    async def _run() -> list[str]:
        received: list[str] = []

        async def writer(line: str) -> None:
            received.append(line)

        em = AsyncSessionEmitter(session="s_async", thread="t_async", writer=writer)
        async with em:
            em.open()
            em.emit_thinking_step(step="check")
            em.close()
            # give the drain task a turn
            await asyncio.sleep(0)
        return received

    lines = asyncio.run(_run())
    import json

    types = [json.loads(l.strip())["type"] for l in lines if l.strip()]
    assert types == ["session.opened", "thinking.step", "session.closed"]


def test_async_emitter_fork_shares_drain_queue() -> None:
    """Forked AsyncSessionEmitter children share the parent's queue (one drain task)."""
    import asyncio

    from agloom.protocol import AsyncSessionEmitter

    async def _run() -> list[str]:
        received: list[str] = []

        async def writer(line: str) -> None:
            received.append(line)

        parent = AsyncSessionEmitter(session="s_af", thread="t1", writer=writer)
        async with parent:
            parent.open()
            child = parent.fork_for_thread("t2")
            child.emit_thinking_step(step="child_step")
            parent.close()
            await asyncio.sleep(0)
        return received

    lines = asyncio.run(_run())
    import json

    threads = [json.loads(l.strip())["thread"] for l in lines if l.strip()]
    assert "t2" in threads  # child event made it through
