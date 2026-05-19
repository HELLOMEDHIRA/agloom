"""Workers inherit L2 HITL middleware from parent invoke_config."""

from __future__ import annotations

from unittest.mock import MagicMock

from agloom.worker import _hitl_middleware_for_invoke


def test_hitl_middleware_empty_without_parent() -> None:
    assert _hitl_middleware_for_invoke(None, "w1") == []


def test_hitl_middleware_builds_from_parent_dict() -> None:
    allow: set[str] = set()
    parent = {
        "interrupt_before_tools": ["tools"],
        "user_callback": MagicMock(),
        "_hitl_tool_allowlist": allow,
        "name": "Parent",
    }
    chain = _hitl_middleware_for_invoke({"_hitl_parent": parent}, "worker_a")
    assert len(chain) == 1
    mw = chain[0]
    assert mw.agent_name == "Parent:worker_a"
    assert mw.tool_allowlist is allow
