"""Tests for ``HumanApprovalMiddleware`` — request-shape compatibility and pause/skip logic.

LangChain's ``ToolCallRequest`` shape changed between major versions; the middleware must read
``tool_call`` (a ``ToolCall`` dict) on >=1.x while still supporting the older flat shape used by
forks / earlier releases. These tests pin both paths.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from agloom.hitl_contract import HITLEvent
from agloom.patterns.middleware import HumanApprovalMiddleware, UserAbort


def _make_request_v1(name: str, args: dict[str, Any], tool_call_id: str | None = None) -> Any:
    """LangChain >=1.x shape: ``request.tool_call`` is a ``ToolCall`` dict."""
    tool_call: dict[str, Any] = {"name": name, "args": args}
    if tool_call_id is not None:
        tool_call["id"] = tool_call_id
    return SimpleNamespace(
        tool_call=tool_call,
        tool=SimpleNamespace(name=name),
        state=None,
        runtime=None,
    )


def _make_request_legacy(name: str, args: dict[str, Any], tool_call_id: str | None = None) -> Any:
    """Pre-1.x flat shape: ``request.name`` / ``request.args`` / ``request.tool_call_id``."""
    return SimpleNamespace(name=name, args=args, tool_call_id=tool_call_id, tool=None)


def test_extract_tool_call_v1_shape() -> None:
    req = _make_request_v1("read_file", {"path": "pyproject.toml"}, tool_call_id="tc_42")
    name, args, tcid = HumanApprovalMiddleware._extract_tool_call(req)
    assert name == "read_file"
    assert args == {"path": "pyproject.toml"}
    assert tcid == "tc_42"


def test_extract_tool_call_legacy_shape() -> None:
    req = _make_request_legacy("run_shell", {"cmd": "ls"}, tool_call_id="tc_legacy")
    name, args, tcid = HumanApprovalMiddleware._extract_tool_call(req)
    assert name == "run_shell"
    assert args == {"cmd": "ls"}
    assert tcid == "tc_legacy"


def test_extract_tool_call_falls_back_to_basetool_name() -> None:
    """When neither ``tool_call`` nor flat fields carry a name, fall through to ``request.tool.name``."""
    req = SimpleNamespace(tool_call=None, tool=SimpleNamespace(name="grep_files"))
    name, args, tcid = HumanApprovalMiddleware._extract_tool_call(req)
    assert name == "grep_files"
    assert args == {}
    assert tcid is None


def test_extract_tool_call_unknown_name_default() -> None:
    req = SimpleNamespace(tool_call=None, tool=None)
    name, args, tcid = HumanApprovalMiddleware._extract_tool_call(req)
    assert name == "unknown_tool"
    assert args == {}
    assert tcid is None


def test_awrap_tool_call_skips_when_not_in_interrupt_list() -> None:
    """Tools not listed in ``interrupt_before_tools`` should pass straight through to the handler."""
    mw = HumanApprovalMiddleware(
        interrupt_before_tools=["dangerous_tool"],
        user_callback=lambda *_a, **_kw: "continue",
        agent_name="t",
    )

    handler_called = {"n": 0}

    async def handler(req: Any) -> str:
        handler_called["n"] += 1
        return "ok"

    req = _make_request_v1("safe_tool", {})
    result = asyncio.run(mw.awrap_tool_call(req, handler))
    assert result == "ok"
    assert handler_called["n"] == 1


def test_awrap_tool_call_pauses_on_wildcard() -> None:
    """``"tools"`` in the interrupt list is the wildcard — pause for *every* tool."""
    seen_event: list[str] = []
    seen_payload: list[Any] = []

    async def callback(event: str, payload: Any) -> str:
        seen_event.append(event)
        seen_payload.append(payload)
        return "continue"

    mw = HumanApprovalMiddleware(
        interrupt_before_tools=["tools"],
        user_callback=callback,
        agent_name="agent_x",
    )

    async def handler(req: Any) -> str:
        return "tool_result"

    req = _make_request_v1("read_file", {"path": "foo"}, tool_call_id="abc")
    result = asyncio.run(mw.awrap_tool_call(req, handler))
    assert result == "tool_result"
    assert seen_event == [HITLEvent.TOOL_INTERRUPT_BEFORE]
    payload = seen_payload[0]
    assert payload["tool_name"] == "read_file"
    assert payload["tool_call_id"] == "abc"
    assert payload["agent_name"] == "agent_x"
    assert payload["args"] == {"path": "foo"}


def test_awrap_tool_call_aborts_on_user_reject() -> None:
    async def callback(event: str, payload: Any) -> str:
        return "abort"

    mw = HumanApprovalMiddleware(
        interrupt_before_tools=["tools"],
        user_callback=callback,
        agent_name="t",
    )

    async def handler(req: Any) -> str:
        pytest.fail("handler must not run after user abort")
        return "should-not-reach"

    req = _make_request_v1("read_file", {"path": "x"})
    with pytest.raises(UserAbort):
        asyncio.run(mw.awrap_tool_call(req, handler))


def test_awrap_tool_call_callback_failure_aborts_safely() -> None:
    """Callback errors → UserAbort (do NOT silently auto-approve)."""

    async def failing_callback(event: str, payload: Any) -> str:
        raise RuntimeError("ui crashed")

    mw = HumanApprovalMiddleware(
        interrupt_before_tools=["tools"],
        user_callback=failing_callback,
        agent_name="t",
    )

    async def handler(req: Any) -> str:
        pytest.fail("handler must not run after callback failure")
        return "should-not-reach"

    req = _make_request_v1("read_file", {"path": "x"})
    with pytest.raises(UserAbort, match="HITL prompt failed"):
        asyncio.run(mw.awrap_tool_call(req, handler))
