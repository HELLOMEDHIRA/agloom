"""AGP ``done`` payload: wire-safe ``ExecutionResult.messages`` serialization."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agloom.models import ExecutionResult, PatternType
from agloom.wire_execution_result import (
    chat_message_wire_dict,
    execution_result_wire_dict,
)


def _assert_json_roundtrip(obj: Any) -> None:
    json.dumps(obj)


def test_execution_result_wire_dict_messages_shape() -> None:
    result = ExecutionResult(
        pattern_used=PatternType.DIRECT,
        query="hello",
        output="done",
        messages=[
            HumanMessage(content="hi"),
            AIMessage(
                content="thinking",
                tool_calls=[
                    {
                        "name": "search",
                        "args": {"q": "x"},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content='{"ok": true}', tool_call_id="call_1", name="search"),
        ],
    )
    wire = execution_result_wire_dict(result)
    _assert_json_roundtrip(wire)
    assert wire["output"] == "done"
    msgs = wire["messages"]
    assert len(msgs) == 3
    assert msgs[0]["role"] == "human"
    assert msgs[0]["content"] == "hi"
    assert msgs[0]["lc_class"] == "HumanMessage"
    assert msgs[1]["role"] == "ai"
    assert msgs[1]["content"] == "thinking"
    assert msgs[1]["tool_calls"]
    assert msgs[1]["tool_calls"][0]["name"] == "search"
    assert msgs[1]["tool_calls"][0]["id"] == "call_1"
    assert "args_snippet" in msgs[1]["tool_calls"][0]
    assert msgs[2]["role"] == "tool"
    assert msgs[2]["tool_call_id"] == "call_1"
    assert msgs[2]["name"] == "search"


def test_chat_message_wire_dict_non_message() -> None:
    d = chat_message_wire_dict(42)
    assert d["role"] == "unknown"
    assert "42" in d["content"] or d["content"] == "42"
    assert d["lc_class"] == "int"


def test_multimodal_content_blocks() -> None:
    msg = HumanMessage(content=[{"type": "text", "text": "see"}, {"type": "image_url", "image_url": {}}])
    d = chat_message_wire_dict(msg)
    assert "see" in d["content"]
    assert "[image]" in d["content"]
