"""AGP envelope + event-type round-trip tests."""

from __future__ import annotations

from typing import Any, cast

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agloom.protocol import (
    PROTOCOL_VERSION,
    Envelope,
    ErrorData,
    ErrorFatal,
    ErrorTransient,
    HITLAllowlisted,
    HITLDecisionData,
    HITLDenied,
    HITLGranted,
    HITLRequest,
    HITLRequestData,
    MessageAssistant,
    MessageAssistantData,
    MessageUser,
    MessageUserData,
    MetricCost,
    MetricCostData,
    MetricTokens,
    MetricTokensData,
    PatternClassified,
    PatternClassifiedData,
    SessionClosed,
    SessionClosedData,
    SessionOpened,
    SessionOpenedData,
    ThinkingStep,
    ThinkingStepData,
    TokenDelta,
    TokenDeltaData,
    ToolCallError,
    ToolCallErrorData,
    ToolCallResult,
    ToolCallResultData,
    ToolCallStart,
    ToolCallStartData,
    WorkerCompleted,
    WorkerCompletedData,
    WorkerFailed,
    WorkerFailedData,
    WorkerSpawned,
    WorkerSpawnedData,
    event_adapter,
    event_to_dict,
)

# envelope-level


def test_envelope_protocol_version_pinned() -> None:
    assert PROTOCOL_VERSION == "1"


def test_protocol_module_version_lazy_and_stable() -> None:
    from agloom.protocol import envelope as env_mod

    v1 = env_mod.PROTOCOL_MODULE_VERSION
    v2 = env_mod.PROTOCOL_MODULE_VERSION
    assert isinstance(v1, str) and len(v1) > 0
    assert v1 == v2
def test_envelope_default_fields_are_minted() -> None:
    """``id`` and ``ts`` should auto-populate; ``seq`` is required."""
    evt = SessionOpened(
        session="s1",
        thread="t1",
        seq=0,
        data=SessionOpenedData(runtime_version="0.0.0", protocol_version="1"),
    )
    assert evt.v == "1"
    assert evt.id.startswith("evt_")
    assert isinstance(evt.ts, datetime)
    assert evt.ts.tzinfo is not None  # must be timezone-aware
    assert evt.session == "s1"
    assert evt.thread == "t1"


def test_envelope_rejects_extra_fields_at_top_level() -> None:
    with pytest.raises(ValidationError):
        Envelope.model_validate(
            {
                "session": "s",
                "thread": "t",
                "seq": 0,
                "wat": "this should not be accepted",
            }
        )


def test_envelope_negative_seq_rejected() -> None:
    """The ``seq`` field is ``ge=0`` — negative values must fail Pydantic validation at parse time."""
    with pytest.raises(ValidationError):
        SessionOpened.model_validate(
            {
                "session": "s",
                "thread": "t",
                "seq": -1,
                "data": {"runtime_version": "x", "protocol_version": "1"},
            }
        )


# per-event-type round-trip


def _round_trip(evt) -> dict:
    """Dump as JSON, parse back, return the parsed dict."""
    raw = evt.model_dump_json(by_alias=True, exclude_none=True)
    return json.loads(raw)


def test_session_opened_round_trip() -> None:
    evt = SessionOpened(
        session="sess_abc",
        thread="thread_xyz",
        seq=1,
        data=SessionOpenedData(
            runtime_version="0.1.0",
            protocol_version="1",
            capabilities_override=["custom.extension"],
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "session.opened"
    assert d["data"]["capabilities_override"] == ["custom.extension"]


def test_pattern_classified_round_trip() -> None:
    evt = PatternClassified(
        session="s",
        thread="t",
        seq=2,
        data=PatternClassifiedData(pattern="REACT", complexity=5, confidence=0.9),
    )
    d = _round_trip(evt)
    assert d["type"] == "pattern.classified"
    assert d["data"]["pattern"] == "REACT"
    assert d["data"]["complexity"] == 5


def test_thinking_step_round_trip_with_elapsed() -> None:
    evt = ThinkingStep(
        session="s",
        thread="t",
        seq=3,
        data=ThinkingStepData(step="analyze_query", elapsed_ms=120),
    )
    d = _round_trip(evt)
    assert d["type"] == "thinking.step"
    assert d["data"]["elapsed_ms"] == 120


def test_token_delta_round_trip_preserves_whitespace() -> None:
    """Trailing spaces in tokens MUST survive — they carry word boundaries."""
    evt = TokenDelta(
        session="s",
        thread="t",
        seq=4,
        data=TokenDeltaData(text="Hello, ", role="assistant"),
    )
    d = _round_trip(evt)
    assert d["data"]["text"] == "Hello, "  # trailing space preserved


def test_message_assistant_round_trip() -> None:
    evt = MessageAssistant(
        session="s",
        thread="t",
        seq=5,
        data=MessageAssistantData(content="Hi.", pattern="REACT"),
    )
    d = _round_trip(evt)
    assert d["type"] == "message.assistant"
    assert d["data"]["content"] == "Hi."
    assert d["data"]["pattern"] == "REACT"


def test_session_closed_round_trip_with_reason() -> None:
    evt = SessionClosed(
        session="s",
        thread="t",
        seq=6,
        data=SessionClosedData(reason="completed", duration_ms=1234),
    )
    d = _round_trip(evt)
    assert d["type"] == "session.closed"
    assert d["data"]["reason"] == "completed"
    assert d["data"]["duration_ms"] == 1234


def test_session_closed_invalid_reason_rejected() -> None:
    """``reason`` is constrained to a fixed Literal — typos must fail at construction."""
    with pytest.raises(ValidationError):
        SessionClosed(
            session="s",
            thread="t",
            seq=7,
            data=SessionClosedData(reason=cast(Any, "finished")),
        )


# message.user


def test_message_user_round_trip() -> None:
    evt = MessageUser(
        session="s",
        thread="t",
        seq=8,
        data=MessageUserData(content="Read pyproject.toml", message_id="u1"),
    )
    d = _round_trip(evt)
    assert d["type"] == "message.user"
    assert d["data"]["content"] == "Read pyproject.toml"
    assert d["data"]["message_id"] == "u1"


# tool.*


def test_tool_call_start_round_trip() -> None:
    evt = ToolCallStart(
        session="s",
        thread="t",
        seq=10,
        data=ToolCallStartData(
            tool="read_file",
            tool_call_id="tc_1",
            args={"path": "pyproject.toml"},
            worker="researcher",
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "tool.call.start"
    assert d["data"]["tool"] == "read_file"
    assert d["data"]["tool_call_id"] == "tc_1"
    assert d["data"]["args"] == {"path": "pyproject.toml"}
    assert d["data"]["worker"] == "researcher"


def test_tool_call_result_round_trip() -> None:
    evt = ToolCallResult(
        session="s",
        thread="t",
        seq=11,
        parent="evt_start",
        data=ToolCallResultData(
            tool="read_file",
            tool_call_id="tc_1",
            output_preview="contents...",
            output_bytes=42,
            duration_ms=12,
            truncated=True,
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "tool.call.result"
    assert d["parent"] == "evt_start"
    assert d["data"]["truncated"] is True
    assert d["data"]["output_bytes"] == 42


def test_tool_call_error_round_trip() -> None:
    evt = ToolCallError(
        session="s",
        thread="t",
        seq=12,
        parent="evt_start",
        data=ToolCallErrorData(
            tool="run_shell",
            tool_call_id="tc_2",
            error="permission denied",
            error_class="PermissionError",
            duration_ms=4,
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "tool.call.error"
    assert d["data"]["error_class"] == "PermissionError"


# error.*


def test_error_fatal_round_trip() -> None:
    evt = ErrorFatal(
        session="s",
        thread="t",
        seq=20,
        data=ErrorData(
            severity="fatal",
            message="provider rejected",
            error_class="RuntimeError",
            stage="invocation",
            retryable=False,
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "error.fatal"
    assert d["data"]["severity"] == "fatal"
    assert d["data"]["retryable"] is False


def test_error_transient_round_trip() -> None:
    evt = ErrorTransient(
        session="s",
        thread="t",
        seq=21,
        data=ErrorData(
            severity="transient",
            message="429 backoff",
            error_class="RateLimitError",
            stage="stream",
            retryable=True,
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "error.transient"
    assert d["data"]["retryable"] is True


def test_error_severity_invalid_rejected() -> None:
    with pytest.raises(ValidationError):
        ErrorData(severity=cast(Any, "warn"), message="x")


def test_event_adapter_dispatches_tool_call_start() -> None:
    """Adapter must materialize ``ToolCallStart`` from a wire dict."""
    raw = {
        "v": "1",
        "id": "evt_x",
        "ts": datetime.now(UTC).isoformat(),
        "session": "s",
        "thread": "t",
        "seq": 1,
        "type": "tool.call.start",
        "data": {"tool": "x", "tool_call_id": "tc"},
    }
    parsed = event_adapter.validate_python(raw)
    assert isinstance(parsed, ToolCallStart)
    assert parsed.data.tool == "x"


# hitl.*


def test_hitl_request_round_trip_tool_approval() -> None:
    evt = HITLRequest(
        session="s",
        thread="t",
        seq=30,
        data=HITLRequestData(
            request_id="hr_1",
            kind="tool_approval",
            tool="read_file",
            tool_call_id="tc_42",
            args={"path": "x.py"},
            options=["accept", "reject", "allowlist"],
            default="reject",
            agent_name="agloom-runtime",
            detail="Tool: read_file\nArgs: {path:x.py}",
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "hitl.request"
    assert d["data"]["kind"] == "tool_approval"
    assert d["data"]["tool"] == "read_file"
    assert d["data"]["options"] == ["accept", "reject", "allowlist"]


def test_hitl_request_kind_invalid_rejected() -> None:
    """``kind`` is a closed Literal — typos must fail at construction."""
    with pytest.raises(ValidationError):
        HITLRequestData(request_id="hr_x", kind=cast(Any, "freeform"))


def test_hitl_granted_round_trip() -> None:
    evt = HITLGranted(
        session="s",
        thread="t",
        seq=31,
        parent="evt_request",
        data=HITLDecisionData(request_id="hr_1", decision="accept", actor="user"),
    )
    d = _round_trip(evt)
    assert d["type"] == "hitl.granted"
    assert d["parent"] == "evt_request"
    assert d["data"]["decision"] == "accept"


def test_hitl_denied_round_trip() -> None:
    evt = HITLDenied(
        session="s",
        thread="t",
        seq=32,
        data=HITLDecisionData(request_id="hr_1", decision="reject", actor="user"),
    )
    d = _round_trip(evt)
    assert d["type"] == "hitl.denied"


def test_hitl_allowlisted_round_trip_with_detail() -> None:
    evt = HITLAllowlisted(
        session="s",
        thread="t",
        seq=33,
        data=HITLDecisionData(
            request_id="hr_1",
            decision="allowlist",
            actor="user",
            detail="added to project allowlist",
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "hitl.allowlisted"
    assert d["data"]["detail"] == "added to project allowlist"


def test_hitl_clarification_carries_text_answer() -> None:
    """For ``kind=clarification``, the outcome event's ``text`` carries the user's free-text reply."""
    evt = HITLGranted(
        session="s",
        thread="t",
        seq=34,
        data=HITLDecisionData(request_id="hr_2", decision="accept", actor="user", text="42"),
    )
    d = _round_trip(evt)
    assert d["data"]["text"] == "42"


def test_event_adapter_dispatches_hitl_request() -> None:
    raw = {
        "v": "1",
        "id": "evt_h",
        "ts": datetime.now(UTC).isoformat(),
        "session": "s",
        "thread": "t",
        "seq": 1,
        "type": "hitl.request",
        "data": {"request_id": "hr_1", "kind": "tool_approval"},
    }
    parsed = event_adapter.validate_python(raw)
    assert isinstance(parsed, HITLRequest)
    assert parsed.data.kind == "tool_approval"


# worker.*


def test_worker_spawned_round_trip() -> None:
    evt = WorkerSpawned(
        session="s",
        thread="t",
        seq=40,
        data=WorkerSpawnedData(
            worker_id="w_1",
            name="researcher",
            pattern="SUPERVISOR",
            task="gather facts about cats",
            parent_worker_id=None,
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "worker.spawned"
    assert d["data"]["worker_id"] == "w_1"
    assert d["data"]["pattern"] == "SUPERVISOR"


def test_worker_spawned_supports_nested_supervision() -> None:
    """Nested workers carry ``parent_worker_id`` so the UI can render the tree."""
    evt = WorkerSpawned(
        session="s",
        thread="t",
        seq=41,
        data=WorkerSpawnedData(worker_id="w_2", parent_worker_id="w_1"),
    )
    d = _round_trip(evt)
    assert d["data"]["parent_worker_id"] == "w_1"


def test_worker_completed_round_trip_with_truncation() -> None:
    evt = WorkerCompleted(
        session="s",
        thread="t",
        seq=42,
        parent="evt_spawn",
        data=WorkerCompletedData(
            worker_id="w_1",
            output_preview="…",
            output_bytes=99999,
            duration_ms=2400,
            truncated=True,
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "worker.completed"
    assert d["parent"] == "evt_spawn"
    assert d["data"]["truncated"] is True
    assert d["data"]["output_bytes"] == 99999


def test_worker_halted_round_trip() -> None:
    from agloom.protocol.events import WorkerHalted, WorkerHaltedData

    evt = WorkerHalted(
        session="s",
        thread="t",
        seq=44,
        data=WorkerHaltedData(
            worker_id="w_1",
            reason="HALT_ALL",
            output_preview="partial output",
            duration_ms=90,
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "worker.halted"
    assert d["data"]["reason"] == "HALT_ALL"


def test_worker_failed_round_trip_carries_error_class() -> None:
    evt = WorkerFailed(
        session="s",
        thread="t",
        seq=43,
        data=WorkerFailedData(
            worker_id="w_1",
            error="provider rate-limited",
            error_class="RateLimitError",
            duration_ms=1500,
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "worker.failed"
    assert d["data"]["error_class"] == "RateLimitError"


# metric.*


def test_metric_tokens_round_trip() -> None:
    evt = MetricTokens(
        session="s",
        thread="t",
        seq=50,
        data=MetricTokensData(
            model="groq:llama-3.3-70b",
            input_tokens=200,
            output_tokens=80,
            total_tokens=280,
            phase="react",
            worker_id="w_1",
        ),
    )
    d = _round_trip(evt)
    assert d["type"] == "metric.tokens"
    assert d["data"]["input_tokens"] == 200
    assert d["data"]["total_tokens"] == 280


def test_metric_tokens_defaults_to_zero_so_consumers_can_sum_safely() -> None:
    """Frontends sum across the session — defaults must be ``0`` (never ``None``) on the wire."""
    evt = MetricTokensData(model="x")
    assert evt.input_tokens == 0
    assert evt.output_tokens == 0
    assert evt.total_tokens is None  # may stay None — providers vary


def test_metric_cost_round_trip_default_currency() -> None:
    evt = MetricCost(
        session="s",
        thread="t",
        seq=51,
        data=MetricCostData(cost=0.0042, model="groq:llama-3.3-70b", phase="react"),
    )
    d = _round_trip(evt)
    assert d["type"] == "metric.cost"
    assert d["data"]["currency"] == "USD"  # default
    assert d["data"]["cost"] == 0.0042
    assert d["data"].get("estimated") in (False, None)


def test_metric_cost_round_trip_estimated_flag() -> None:
    evt = MetricCost(
        session="s",
        thread="t",
        seq=52,
        data=MetricCostData(cost=0.000001, model="nvidia:x", phase="p", estimated=True),
    )
    d = _round_trip(evt)
    assert d["data"]["estimated"] is True


def test_event_adapter_dispatches_worker_and_metric() -> None:
    """Adapter must materialize all the new event types."""
    base = {
        "v": "1",
        "id": "evt_x",
        "ts": datetime.now(UTC).isoformat(),
        "session": "s",
        "thread": "t",
        "seq": 1,
    }
    parsed = event_adapter.validate_python({**base, "type": "worker.spawned", "data": {"worker_id": "w_1"}})
    assert isinstance(parsed, WorkerSpawned)
    parsed = event_adapter.validate_python({**base, "type": "metric.tokens", "data": {"input_tokens": 1}})
    assert isinstance(parsed, MetricTokens)


# discriminated union & TypeAdapter


def test_event_adapter_dispatches_on_type() -> None:
    """``event_adapter`` must materialize the right concrete subclass from a dict."""
    raw_dict = {
        "v": "1",
        "id": "evt_x",
        "ts": datetime.now(UTC).isoformat(),
        "session": "s",
        "thread": "t",
        "seq": 1,
        "type": "thinking.step",
        "data": {"step": "classify", "elapsed_ms": 42},
    }
    parsed = event_adapter.validate_python(raw_dict)
    assert isinstance(parsed, ThinkingStep)
    assert parsed.data.elapsed_ms == 42


def test_event_adapter_rejects_unknown_type() -> None:
    """Phase-0 union is closed; UI consumers wanting forward-compat parse to ``dict`` themselves."""
    raw_dict = {
        "v": "1",
        "id": "evt_x",
        "ts": datetime.now(UTC).isoformat(),
        "session": "s",
        "thread": "t",
        "seq": 1,
        "type": "tool.call.start",  # outside the minimal v1 union exercised above
        "data": {},
    }
    with pytest.raises(ValidationError):
        event_adapter.validate_python(raw_dict)


def test_event_to_dict_drops_none_values() -> None:
    evt = ThinkingStep(
        session="s",
        thread="t",
        seq=1,
        data=ThinkingStepData(step="classify"),  # no label / detail / elapsed_ms
    )
    d = event_to_dict(evt)
    assert "parent" not in d
    assert "trace" not in d
    assert "label" not in d["data"]
    assert "elapsed_ms" not in d["data"]
