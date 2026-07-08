"""System-first message invariant for strict chat templates (vLLM/LiteLLM/Qwen)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agloom.llm.chat_template_compat import (
    _is_system_message,
    ensure_messages_for_chat_template,
    repair_react_graph_state,
)


def _sys_pos(msgs: list) -> list[int]:
    return [i for i, m in enumerate(msgs) if _is_system_message(m)]


def test_ensure_messages_forces_single_leading_system() -> None:
    out = ensure_messages_for_chat_template(
        [
            HumanMessage(content="do the thing"),
            SystemMessage(content="you are a helpful agent"),
            AIMessage(content="ok"),
        ]
    )
    assert _sys_pos(out) == [0]


def test_repair_keeps_system_first_when_reinserting_user_turn() -> None:
    out = repair_react_graph_state(
        [
            SystemMessage(content="sys"),
            AIMessage(content="prev"),
            ToolMessage(content="t", tool_call_id="1", name="x"),
        ],
        query="please continue",
    )
    assert _sys_pos(out) == [0]
