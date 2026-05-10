"""Tests for detecting model turns that emit tool JSON as plain text (NVIDIA / some Llama endpoints)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agloom.patterns.react_tool_recovery import (
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
