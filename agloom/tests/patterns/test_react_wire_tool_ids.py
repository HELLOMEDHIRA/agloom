"""ReAct wire tool_call_id correlation (stream run_id vs message tool_call_id)."""

from __future__ import annotations

from agloom.models import StepType, _make_step
from agloom.patterns.react import _resolve_wire_tool_call_id_for_step


def test_resolve_wire_tool_call_id_remaps_result_to_stream_call() -> None:
    stream_id = "0192-run-uuid"
    call = _make_step(
        StepType.TOOL_CALL,
        "mkdir",
        input='{"path": "a/b"}',
        id=stream_id,
        wire_emitted=True,
    )
    result = _make_step(
        StepType.TOOL_RESULT,
        "mkdir",
        output="ok",
        id="call_langchain_abc",
    )
    assert _resolve_wire_tool_call_id_for_step(result, [call, result]) == stream_id
