"""Workers in reflection/supervisor/etc. inherit forced tool_choice on user turns."""

from __future__ import annotations

from unittest.mock import MagicMock

from agloom.patterns.middleware import ReactUserTurnToolChoiceMiddleware
from agloom.worker import _worker_react_middleware, extend_invoke_config_with_event_queue


def test_worker_react_middleware_includes_tool_choice_by_default() -> None:
    chain = _worker_react_middleware(None, "worker_1")
    assert any(isinstance(m, ReactUserTurnToolChoiceMiddleware) for m in chain)


def test_worker_react_middleware_respects_parent_flag_false() -> None:
    chain = _worker_react_middleware(
        {"react_force_tool_choice_on_user_turn": False},
        "worker_1",
    )
    assert not any(isinstance(m, ReactUserTurnToolChoiceMiddleware) for m in chain)


def test_worker_react_middleware_includes_hitl_when_parent_set() -> None:
    from agloom.patterns.middleware import HumanApprovalMiddleware

    parent = {
        "interrupt_before_tools": ["tools"],
        "user_callback": MagicMock(),
        "_hitl_tool_allowlist": set(),
        "name": "Parent",
    }
    chain = _worker_react_middleware({"_hitl_parent": parent}, "worker_a")
    assert any(isinstance(m, ReactUserTurnToolChoiceMiddleware) for m in chain)
    assert any(isinstance(m, HumanApprovalMiddleware) for m in chain)


def test_extend_invoke_config_forwards_react_force_tool_choice() -> None:
    agent = {"react_force_tool_choice_on_user_turn": False, "name": "t"}
    merged = extend_invoke_config_with_event_queue(None, MagicMock(), agent=agent)
    assert merged is not None
    assert merged["react_force_tool_choice_on_user_turn"] is False
