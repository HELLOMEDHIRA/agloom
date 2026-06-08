"""Tests for detecting model turns that emit tool JSON as plain text (NVIDIA / some Llama endpoints)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from langchain_core.messages import ToolMessage as LCToolMessage

from agloom.patterns.react import _fallback_output_from_messages, _tool_output_to_wire_text
from agloom.patterns.react_tool_recovery import (
    is_stray_tool_json_text,
    last_ai_message_is_stray_tool_json,
)


def test_stray_openai_style_type_function() -> None:
    msgs = [
        HumanMessage(content="read file"),
        AIMessage(
            content='{"type": "function", "name": "read_file", "parameters": {"path": "x.txt"}}'
        ),
    ]
    assert last_ai_message_is_stray_tool_json(msgs, frozenset({"read_file"})) is True


def test_stray_name_parameters_only() -> None:
    msgs = [
        HumanMessage(content="again"),
        AIMessage(content='{"name": "read_file", "parameters": {"path": "p.toml", "offset": 21, "limit": 20}}'),
    ]
    assert last_ai_message_is_stray_tool_json(msgs, frozenset({"read_file"})) is True


def test_not_stray_when_structured_tool_calls_present() -> None:
    msgs = [
        HumanMessage(content="x"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_file", "args": {"path": "a"}, "id": "1", "type": "tool_call"},
            ],
        ),
    ]
    assert last_ai_message_is_stray_tool_json(msgs, frozenset({"read_file"})) is False


def test_not_stray_for_normal_prose() -> None:
    msgs = [HumanMessage(content="x"), AIMessage(content="Here is the answer in plain text.")]
    assert last_ai_message_is_stray_tool_json(msgs, frozenset({"read_file"})) is False


def test_not_stray_unknown_tool_name() -> None:
    msgs = [
        HumanMessage(content="x"),
        AIMessage(content='{"name": "other_tool", "parameters": {}}'),
    ]
    assert last_ai_message_is_stray_tool_json(msgs, frozenset({"read_file"})) is False


def test_false_when_last_message_is_tool_result() -> None:
    msgs = [
        HumanMessage(content="x"),
        AIMessage(content="..."),
        ToolMessage(content="ok", tool_call_id="1", name="read_file"),
    ]
    assert last_ai_message_is_stray_tool_json(msgs, frozenset({"read_file"})) is False


def test_empty_allowed_names() -> None:
    msgs = [HumanMessage(content="x"), AIMessage(content='{"name": "read_file", "parameters": {}}')]
    assert last_ai_message_is_stray_tool_json(msgs, frozenset()) is False


def test_is_stray_tool_json_text_matches_screenshot_shape() -> None:
    text = (
        '{"type": "function", "name": "read_file", '
        '"parameters": {"path": "pyproject.toml", "line_cap": 20, "limit": 400}}'
    )
    assert is_stray_tool_json_text(text, frozenset({"read_file"})) is True


def test_tool_output_to_wire_text_uses_message_content_not_repr() -> None:
    body = "[agloom:tool_result] complete=true\n1|[project]\n2|name = agloom"
    tm = LCToolMessage(content=body, tool_call_id="tc1", name="read_file")
    out = _tool_output_to_wire_text(tm)
    assert out.startswith("[agloom:tool_result]")
    assert "content=" not in out


def test_fallback_output_from_messages_after_stray_json() -> None:
    body = "[agloom:tool_result] complete=true\n1|[project]\n2|name = agloom"
    msgs = [
        HumanMessage(content="read"),
        AIMessage(
            content='{"type": "function", "name": "read_file", "parameters": {"path": "pyproject.toml"}}'
        ),
        LCToolMessage(content=body, tool_call_id="tc1", name="read_file"),
        AIMessage(
            content='{"type": "function", "name": "read_file", "parameters": {"path": "pyproject.toml", "line_cap": 20}}'
        ),
    ]
    fb = _fallback_output_from_messages(msgs, tool_names=frozenset({"read_file"}))
    assert fb is not None
    assert "1|[project]" in fb
