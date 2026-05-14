"""Runtime bridge — translator branches + end-to-end fake-agent invocation."""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterable

import pytest

from agloom.models import AgentEvent
from agloom.protocol import (
    ErrorFatal,
    MessageAssistant,
    MessageUser,
    MetricTokens,
    PatternClassified,
    PromptCancelled,
    PromptRequested,
    SessionClosed,
    SessionEmitter,
    SessionOpened,
    ThinkingStep,
    TokenDelta,
    ToolCallError,
    ToolCallResult,
    ToolCallStart,
    WorkerCompleted,
    WorkerFailed,
    WorkerSpawned,
    event_adapter,
)
from agloom.runtime import run_invocation_to_writer
from agloom.runtime.bridge import run_invocation
from agloom.runtime.hitl import HITLBridge
from agloom.runtime.translator import translate

# translator unit tests


class _CaptureEmitter:
    """Minimal stand-in: records typed-emit calls without writing to a stream."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name: str):
        if not name.startswith("emit_"):
            raise AttributeError(name)

        def fn(**kwargs):
            self.calls.append((name, kwargs))

        return fn


def test_translate_classify_emits_pattern_then_thinking() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(type="classify", data={"pattern": "REACT", "complexity": 5, "output": "ok"}),
        em,  # type: ignore[arg-type]
    )
    assert [name for name, _ in em.calls] == ["emit_pattern_classified", "emit_thinking_step"]
    assert em.calls[0][1]["pattern"] == "REACT"
    assert em.calls[0][1]["complexity"] == 5


def test_translate_token_preserves_whitespace() -> None:
    em = _CaptureEmitter()
    translate(AgentEvent(type="token", data={"output": "Hello, "}), em)  # type: ignore[arg-type]
    assert em.calls == [("emit_token_delta", {"text": "Hello, ", "role": "assistant", "message_id": None})]


def test_translate_token_content_key() -> None:
    """``content`` key is the production key emitted by unified_agent/worker/patterns."""
    em = _CaptureEmitter()
    translate(AgentEvent(type="token", data={"content": " World!"}), em)  # type: ignore[arg-type]
    assert em.calls == [("emit_token_delta", {"text": " World!", "role": "assistant", "message_id": None})]


def test_translate_token_text_key_fallback() -> None:
    """``text`` key is a legacy fallback that must still work."""
    em = _CaptureEmitter()
    translate(AgentEvent(type="token", data={"text": "foo"}), em)  # type: ignore[arg-type]
    assert em.calls == [("emit_token_delta", {"text": "foo", "role": "assistant", "message_id": None})]


def test_translate_llm_call_emits_estimated_metric_cost_when_usage_present() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(
            type="llm_call",
            data={
                "name": "direct_shortcircuit",
                "model": "nvidia:meta/llama-4-maverick-17b-128e-instruct",
                "usage": {"input_tokens": 1, "output_tokens": 16, "total_tokens": 17},
            },
        ),
        em,  # type: ignore[arg-type]
    )
    names = [c[0] for c in em.calls]
    assert "emit_metric_tokens" in names
    assert "emit_metric_cost" in names
    cost_call = next(c for c in em.calls if c[0] == "emit_metric_cost")
    assert cost_call[1]["cost"] > 0.0
    assert cost_call[1]["estimated"] is True


def test_translate_done_emits_message_assistant() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(type="done", data={"output": "Final answer", "pattern": "REACT"}),
        em,  # type: ignore[arg-type]
    )
    assert em.calls == [
        ("emit_message_assistant", {"content": "Final answer", "message_id": None, "run_id": None, "pattern": "REACT"})
    ]


def test_translate_skill_context_emits_skill_applied() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(type="skill_context", data={"phase": "classifier", "injected_chars": 120}),
        em,  # type: ignore[arg-type]
    )
    assert em.calls == [("emit_skill_applied", {"phase": "classifier", "injected_chars": 120})]


def test_translate_skill_learned_emits_skill_learned() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(
            type="skill_learned",
            data={"skill_name": "foo_bar", "pattern": "react", "scope": "global", "source": "post_run"},
        ),
        em,  # type: ignore[arg-type]
    )
    assert em.calls == [
        (
            "emit_skill_learned",
            {"skill_name": "foo_bar", "pattern": "react", "scope": "global", "source": "post_run"},
        )
    ]


def test_translate_tool_result_load_skill_emits_skill_loaded() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(
            type="tool_result",
            data={
                "name": "load_skill",
                "id": "tc_1",
                "skill_name": "my_skill",
                "output": "body text here",
            },
        ),
        em,  # type: ignore[arg-type]
    )
    assert [c[0] for c in em.calls] == ["emit_tool_call_result", "emit_skill_loaded", "emit_message_tool"]
    assert em.calls[1] == ("emit_skill_loaded", {"skill_name": "my_skill", "source": "tool", "body_chars": 14})
    assert em.calls[2][0] == "emit_message_tool"


def test_translate_unknown_event_forwarded_as_thinking() -> None:
    """Forward-compat: unknown ``AgentEvent.type`` strings must surface as ``thinking.step``."""
    em = _CaptureEmitter()
    translate(AgentEvent(type="some_future_kind", data={"name": "x"}), em)  # type: ignore[arg-type]
    assert em.calls and em.calls[0][0] == "emit_thinking_step"
    assert em.calls[0][1]["step"] == "some_future_kind"


def test_translate_thinking_event_carries_elapsed_ms() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(type="thinking", data={"name": "analyze_query", "duration_ms": 87}),
        em,  # type: ignore[arg-type]
    )
    assert em.calls and em.calls[0] == (
        "emit_thinking_step",
        {"step": "thinking", "label": "analyze_query", "detail": None, "elapsed_ms": 87},
    )


def test_translate_token_with_empty_text_skipped() -> None:
    em = _CaptureEmitter()
    translate(AgentEvent(type="token", data={"output": ""}), em)  # type: ignore[arg-type]
    assert em.calls == []


def test_translate_token_empty_output_falls_through_to_content() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(type="token", data={"output": "", "content": "x"}),  # type: ignore[arg-type]
        em,
    )
    assert em.calls == [
        ("emit_token_delta", {"text": "x", "role": "assistant", "message_id": None}),
    ]


def test_translate_token_empty_text_falls_through_to_content() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(type="token", data={"text": "", "content": "y"}),  # type: ignore[arg-type]
        em,
    )
    assert em.calls == [
        ("emit_token_delta", {"text": "y", "role": "assistant", "message_id": None}),
    ]


def test_translate_done_nested_result_direct_emits_output() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(
            type="done",
            data={
                "result": {
                    "pattern_used": "DIRECT",
                    "output": "Hello from classifier path",
                    "run_id": "run_1",
                    "query": "Hi",
                    "steps_taken": 1,
                    "success": True,
                },
            },
        ),
        em,  # type: ignore[arg-type]
    )
    assert em.calls == [
        (
            "emit_message_assistant",
            {
                "content": "Hello from classifier path",
                "message_id": None,
                "run_id": "run_1",
                "pattern": "DIRECT",
            },
        ),
    ]


def test_translate_done_nested_result_react_keeps_body_without_top_level_echo() -> None:
    """Nested ``result.output`` must reach the client when there is no top-level duplicate echo."""
    em = _CaptureEmitter()
    translate(
        AgentEvent(
            type="done",
            data={
                "result": {
                    "pattern_used": "REACT",
                    "output": "Final reply only in result",
                    "run_id": "run_2",
                    "query": "q",
                    "steps_taken": 2,
                    "success": True,
                },
            },
        ),
        em,  # type: ignore[arg-type]
    )
    assert em.calls == [
        (
            "emit_message_assistant",
            {
                "content": "Final reply only in result",
                "message_id": None,
                "run_id": "run_2",
                "pattern": "REACT",
            },
        ),
    ]


def test_translate_done_react_suppresses_top_level_duplicate_only() -> None:
    """Top-level ``output`` on ``done`` is dropped for REACT when pattern is known (tokens carry prose)."""
    em = _CaptureEmitter()
    translate(
        AgentEvent(
            type="done",
            data={"output": "Streamed already", "pattern": "REACT", "result": {"pattern_used": "REACT"}},
        ),
        em,  # type: ignore[arg-type]
    )
    assert em.calls == [
        ("emit_message_assistant", {"content": "", "message_id": None, "run_id": None, "pattern": "REACT"}),
    ]


def test_translate_done_falls_back_to_direct_shortcircuit_step_output() -> None:
    em = _CaptureEmitter()
    translate(
        AgentEvent(
            type="done",
            data={
                "result": {
                    "pattern_used": "DIRECT",
                    "output": "",
                    "run_id": "r9",
                    "query": "Hi",
                    "steps_taken": 1,
                    "success": True,
                    "steps": [
                        {
                            "type": "llm_call",
                            "name": "direct_shortcircuit",
                            "input": "Hi",
                            "output": "Hello!",
                            "duration_ms": 0.0,
                            "timestamp": "t",
                            "metadata": {},
                        },
                    ],
                },
            },
        ),
        em,  # type: ignore[arg-type]
    )
    assert em.calls[0][0] == "emit_message_assistant"
    assert em.calls[0][1]["content"] == "Hello!"


# bridge end-to-end tests


class _FakeAgent:
    """Yields a canned :class:`AgentEvent` sequence for deterministic tests."""

    def __init__(self, events: list[AgentEvent], *, raise_after: int | None = None) -> None:
        self._events = events
        self._raise_after = raise_after

    def astream_events(self, query, *, thread_id=None) -> AsyncIterable[AgentEvent]:
        events = list(self._events)
        raise_after = self._raise_after

        async def _gen():
            for i, e in enumerate(events):
                yield e
                # ``raise_after=N`` → raise after N events have been yielded.
                if raise_after is not None and (i + 1) >= raise_after:
                    raise RuntimeError("simulated provider failure")

        return _gen()


def _read_events(buf: io.StringIO) -> list:
    buf.seek(0)
    return [event_adapter.validate_python(json.loads(line)) for line in buf if line.strip()]


@pytest.mark.asyncio
async def test_bridge_full_invocation_emits_prompt_requested_and_assistant() -> None:
    agent = _FakeAgent(
        [
            AgentEvent(type="classify", data={"pattern": "REACT", "complexity": 5, "output": "ok"}),
            AgentEvent(type="thinking", data={"name": "analyze_query", "duration_ms": 12}),
            AgentEvent(type="token", data={"output": "Hello, "}),
            AgentEvent(type="token", data={"output": "world!"}),
            AgentEvent(type="done", data={"output": "Hello, world!", "pattern": "REACT"}),
        ]
    )
    buf = io.StringIO()
    em = await run_invocation_to_writer(agent=agent, prompt="hi", writer=buf)
    events = _read_events(buf)
    assert isinstance(events[0], SessionOpened)
    assert isinstance(events[1], MessageUser)
    assert isinstance(events[2], PromptRequested)
    assert events[2].data.kind == "user_turn"
    assert isinstance(events[-1], SessionClosed)
    assert events[-1].data.reason == "completed"
    assert any(isinstance(e, PatternClassified) for e in events)
    assert any(isinstance(e, ThinkingStep) for e in events)
    assert any(isinstance(e, TokenDelta) for e in events)
    assert any(isinstance(e, MessageAssistant) for e in events)
    assert em.is_open is False
    # ``duration_ms`` should be set (>= 0) on a clean close
    assert events[-1].data.duration_ms is not None
    assert events[-1].data.duration_ms >= 0


@pytest.mark.asyncio
async def test_bridge_synthesizes_message_assistant_when_stream_silent() -> None:
    """Stream that ends without ``done`` should still produce a message.assistant turn boundary."""
    agent = _FakeAgent([AgentEvent(type="thinking", data={"name": "noop"})])
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    types = [e.type for e in events]
    assert types.count("message.assistant") == 1
    # Synthetic message has empty content
    msg = next(e for e in events if e.type == "message.assistant")
    assert msg.data.content == ""


@pytest.mark.asyncio
async def test_bridge_closes_with_error_reason_when_stream_raises() -> None:
    agent = _FakeAgent(
        [
            AgentEvent(type="classify", data={"pattern": "REACT", "complexity": 5, "output": "ok"}),
        ],
        raise_after=1,  # raise on the next yield after the classify event
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    assert isinstance(events[-1], SessionClosed)
    assert events[-1].data.reason == "error"
    assert "simulated provider failure" in (events[-1].data.error or "")


@pytest.mark.asyncio
async def test_bridge_session_and_thread_ids_match_across_events() -> None:
    agent = _FakeAgent([AgentEvent(type="done", data={"output": "ok"})])
    buf = io.StringIO()
    em = await run_invocation_to_writer(
        agent=agent,
        prompt="x",
        thread="thread_pinned",
        session="sess_pinned",
        writer=buf,
    )
    events = _read_events(buf)
    assert {e.session for e in events} == {"sess_pinned"}
    assert {e.thread for e in events} == {"thread_pinned"}
    assert em.session_id == "sess_pinned"
    assert em.thread_id == "thread_pinned"


@pytest.mark.asyncio
async def test_bridge_seq_strictly_monotonic() -> None:
    agent = _FakeAgent(
        [AgentEvent(type="thinking", data={"name": f"step_{i}"}) for i in range(20)]
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))  # no duplicates


# tool.* / message.user / error.* coverage


@pytest.mark.asyncio
async def test_bridge_emits_message_user_with_prompt() -> None:
    """Every invocation must record the user prompt on the wire (replay invariant)."""
    agent = _FakeAgent([AgentEvent(type="done", data={"output": "ok"})])
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="hello world", writer=buf)
    events = _read_events(buf)
    user_msgs = [e for e in events if isinstance(e, MessageUser)]
    assert len(user_msgs) == 1
    assert user_msgs[0].data.content == "hello world"
    # Order: must come after session.opened, before any model output
    types = [e.type for e in events]
    assert types.index("session.opened") < types.index("message.user")
    assert types.index("message.user") < types.index("prompt.requested")
    assert types.index("prompt.requested") < types.index("message.assistant")


@pytest.mark.asyncio
async def test_bridge_dict_prompt_extracts_text_field() -> None:
    """Structured prompts get reduced to their primary text field for ``message.user.content``."""
    agent = _FakeAgent([AgentEvent(type="done", data={"output": "ok"})])
    buf = io.StringIO()
    await run_invocation_to_writer(
        agent=agent, prompt={"input": "structured query"}, writer=buf
    )
    events = _read_events(buf)
    user = next(e for e in events if isinstance(e, MessageUser))
    assert user.data.content == "structured query"


@pytest.mark.asyncio
async def test_bridge_translates_tool_call_and_result() -> None:
    """``tool_call`` / ``tool_result`` AgentEvents land as ``tool.call.start`` / ``tool.call.result``."""
    agent = _FakeAgent(
        [
            AgentEvent(
                type="tool_call",
                data={"name": "read_file", "tool_call_id": "tc_1", "args": {"path": "x"}},
            ),
            AgentEvent(
                type="tool_result",
                data={"name": "read_file", "tool_call_id": "tc_1", "output": "contents", "duration_ms": 7},
            ),
            AgentEvent(type="done", data={"output": "Done."}),
        ]
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    starts = [e for e in events if isinstance(e, ToolCallStart)]
    results = [e for e in events if isinstance(e, ToolCallResult)]
    assert len(starts) == 1
    assert len(results) == 1
    assert starts[0].data.tool == "read_file"
    assert starts[0].data.args == {"path": "x"}
    assert results[0].data.tool_call_id == "tc_1"
    assert results[0].data.duration_ms == 7
    assert results[0].data.output_preview == "contents"


@pytest.mark.asyncio
async def test_bridge_translates_tool_result_with_error_to_tool_call_error() -> None:
    """``tool_result`` carrying an ``error`` key flips to ``tool.call.error`` on the wire."""
    agent = _FakeAgent(
        [
            AgentEvent(
                type="tool_call",
                data={"name": "run_shell", "tool_call_id": "tc_x", "args": {"cmd": "rm /"}},
            ),
            AgentEvent(
                type="tool_result",
                data={
                    "name": "run_shell",
                    "tool_call_id": "tc_x",
                    "error": "permission denied",
                    "error_class": "PermissionError",
                    "duration_ms": 3,
                },
            ),
            AgentEvent(type="done", data={"output": "aborted"}),
        ]
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    errors = [e for e in events if isinstance(e, ToolCallError)]
    results = [e for e in events if isinstance(e, ToolCallResult)]
    assert len(errors) == 1
    assert len(results) == 0
    assert errors[0].data.error == "permission denied"
    assert errors[0].data.error_class == "PermissionError"


# worker.* / metric.* / cancel coverage


@pytest.mark.asyncio
async def test_bridge_translates_worker_start_to_worker_spawned() -> None:
    agent = _FakeAgent(
        [
            AgentEvent(
                type="worker_start",
                data={"worker_id": "w_1", "name": "researcher", "pattern": "SUPERVISOR", "task": "gather facts"},
            ),
            AgentEvent(type="done", data={"output": "Done."}),
        ]
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    spawned = [e for e in events if isinstance(e, WorkerSpawned)]
    assert len(spawned) == 1
    assert spawned[0].data.worker_id == "w_1"
    assert spawned[0].data.pattern == "SUPERVISOR"
    assert spawned[0].data.task == "gather facts"


@pytest.mark.asyncio
async def test_bridge_translates_worker_end_success_to_worker_completed() -> None:
    agent = _FakeAgent(
        [
            AgentEvent(type="worker_start", data={"worker_id": "w_1"}),
            AgentEvent(type="worker_end", data={"worker_id": "w_1", "output": "result text", "duration_ms": 240}),
            AgentEvent(type="done", data={"output": "Done."}),
        ]
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    completed = [e for e in events if isinstance(e, WorkerCompleted)]
    assert len(completed) == 1
    assert completed[0].data.worker_id == "w_1"
    assert completed[0].data.duration_ms == 240
    assert completed[0].data.output_preview == "result text"


@pytest.mark.asyncio
async def test_bridge_translates_worker_end_with_error_to_worker_failed() -> None:
    """Mirror of the tool path: ``worker_end`` carrying ``error`` flips to ``worker.failed``."""
    agent = _FakeAgent(
        [
            AgentEvent(type="worker_start", data={"worker_id": "w_1"}),
            AgentEvent(
                type="worker_end",
                data={"worker_id": "w_1", "error": "rate limited", "error_class": "RateLimitError", "duration_ms": 30},
            ),
            AgentEvent(type="done", data={"output": "aborted"}),
        ]
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    failed = [e for e in events if isinstance(e, WorkerFailed)]
    completed = [e for e in events if isinstance(e, WorkerCompleted)]
    assert len(failed) == 1
    assert len(completed) == 0
    assert failed[0].data.error == "rate limited"
    assert failed[0].data.error_class == "RateLimitError"


@pytest.mark.asyncio
async def test_bridge_llm_call_emits_thinking_step_plus_metric_tokens() -> None:
    """``llm_call`` with ``usage`` → both a ``thinking.step`` and a ``metric.tokens`` event."""
    agent = _FakeAgent(
        [
            AgentEvent(
                type="llm_call",
                data={
                    "name": "classify",
                    "duration_ms": 87,
                    "usage": {"input_tokens": 200, "output_tokens": 80, "total_tokens": 280},
                    "model": "groq:llama-3.3-70b",
                },
            ),
            AgentEvent(type="done", data={"output": "ok"}),
        ]
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    thinks = [e for e in events if isinstance(e, ThinkingStep) and e.data.step == "llm_call"]
    metrics = [e for e in events if isinstance(e, MetricTokens)]
    assert len(thinks) == 1
    assert thinks[0].data.elapsed_ms == 87
    assert len(metrics) == 1
    assert metrics[0].data.input_tokens == 200
    assert metrics[0].data.output_tokens == 80
    assert metrics[0].data.total_tokens == 280
    assert metrics[0].data.model == "groq:llama-3.3-70b"


@pytest.mark.asyncio
async def test_bridge_llm_call_without_usage_emits_only_thinking() -> None:
    """No ``usage`` payload → no spurious ``metric.tokens`` event with all-zero counts."""
    agent = _FakeAgent(
        [
            AgentEvent(type="llm_call", data={"name": "react", "duration_ms": 12}),
            AgentEvent(type="done", data={"output": "ok"}),
        ]
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)
    assert any(isinstance(e, ThinkingStep) and e.data.step == "llm_call" for e in events)
    assert not any(isinstance(e, MetricTokens) for e in events)


@pytest.mark.asyncio
async def test_bridge_cancellation_closes_session_with_user_aborted() -> None:
    """``CancelledError`` propagates out (asyncio invariant) but the bridge still emits a
    ``session.closed(reason="user_aborted")`` boundary on the wire first."""

    async def _slow():
        await asyncio.sleep(10)
        yield AgentEvent(type="done", data={"output": "x"})

    class _SlowAgent:
        def astream_events(self, query, *, thread_id=None):
            return _slow()

    buf = io.StringIO()
    task = asyncio.create_task(
        run_invocation_to_writer(agent=_SlowAgent(), prompt="hi", writer=buf)
    )
    await asyncio.sleep(0)  # let the task start
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    events = _read_events(buf)
    assert isinstance(events[-2], PromptCancelled)
    assert events[-2].data.reason == "user_aborted"
    assert isinstance(events[-1], SessionClosed)
    assert events[-1].data.reason == "user_aborted"
    # No error.fatal — cancellation isn't a failure
    from agloom.protocol import ErrorFatal as _EF
    assert not any(isinstance(e, _EF) for e in events)


@pytest.mark.asyncio
async def test_bridge_shutdown_cancel_emits_prompt_shutdown() -> None:
    """Runtime shutdown path: ``prepare_invocation_cancel(..., shutdown)`` → ``prompt.cancelled`` + ``session.closed`` use ``shutdown``."""

    async def _slow():
        await asyncio.sleep(10)
        yield AgentEvent(type="done", data={"output": "x"})

    class _SlowAgent:
        def astream_events(self, query, *, thread_id=None):
            return _slow()

    buf = io.StringIO()
    root = SessionEmitter(session="sess_sd", thread="main_th", writer=buf, capabilities=[])
    hitl = HITLBridge(root)
    root.open()
    inv_emitter = root.fork_for_thread("inv_th")
    task = asyncio.create_task(
        run_invocation(
            agent=_SlowAgent(),
            prompt="hi",
            thread="inv_th",
            emitter=inv_emitter,
            hitl_bridge=hitl,
        )
    )
    hitl.bind_task_emitter(task, inv_emitter, thread="inv_th")
    await asyncio.sleep(0)
    hitl.prepare_invocation_cancel(task, reason="shutdown")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    events = _read_events(buf)
    pc = [e for e in events if isinstance(e, PromptCancelled)]
    assert pc and pc[-1].data.reason == "shutdown"
    assert pc[-1].data.detail == "runtime_shutdown"
    assert isinstance(events[-1], SessionClosed)
    assert events[-1].data.reason == "shutdown"


@pytest.mark.asyncio
async def test_bridge_emits_error_fatal_then_session_closed_on_exception() -> None:
    """Exception path: ``error.fatal`` first (with class + stage), then ``session.closed`` reason=error."""
    agent = _FakeAgent(
        [AgentEvent(type="classify", data={"pattern": "REACT", "complexity": 5, "output": "ok"})],
        raise_after=1,
    )
    buf = io.StringIO()
    await run_invocation_to_writer(agent=agent, prompt="x", writer=buf)
    events = _read_events(buf)

    fatals = [e for e in events if isinstance(e, ErrorFatal)]
    closes = [e for e in events if isinstance(e, SessionClosed)]
    assert len(fatals) == 1
    assert len(closes) == 1
    # error.fatal must precede session.closed
    types = [e.type for e in events]
    assert types.index("error.fatal") < types.index("session.closed")
    # the fatal carries the exception class
    assert fatals[0].data.error_class == "RuntimeError"
    assert fatals[0].data.stage == "invocation"
    assert "simulated provider failure" in fatals[0].data.message
    # session.closed still has reason=error for backward compat with subscribers that only watch close
    assert closes[0].data.reason == "error"
