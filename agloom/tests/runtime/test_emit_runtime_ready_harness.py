"""``emit_agent_runtime_ready`` always emits explicit ``harness_enabled``."""

from __future__ import annotations

import io
from argparse import Namespace

import pytest

from agloom.protocol import SessionEmitter
from agloom.runtime.session_bootstrap import (
    emit_agent_runtime_ready,
    emit_control_plane_runtime_ready,
)


class _RecordingEmitter(SessionEmitter):
    def __init__(self) -> None:
        super().__init__(session="s", thread="t", writer=io.StringIO())
        self.ready_kw: list[dict] = []

    def emit_runtime_ready(self, **kw):  # type: ignore[no-untyped-def]
        self.ready_kw.append(dict(kw))
        return super().emit_runtime_ready(**kw)


@pytest.mark.asyncio
async def test_emit_agent_runtime_ready_harness_disabled_on_wire() -> None:
    em = _RecordingEmitter()
    agent = type("Agent", (), {"config": {"name": "test-agent", "tools": [], "llm": None}})()
    await emit_agent_runtime_ready(em, agent, harness_enabled=False)
    assert em.ready_kw[-1].get("harness_enabled") is False


@pytest.mark.asyncio
async def test_emit_agent_runtime_ready_harness_enabled_on_wire() -> None:
    em = _RecordingEmitter()
    agent = type("Agent", (), {"config": {"name": "test-agent", "tools": [], "llm": None}})()
    await emit_agent_runtime_ready(em, agent, harness_enabled=True)
    assert em.ready_kw[-1].get("harness_enabled") is True


def test_emit_control_plane_runtime_ready_harness_and_sidebar() -> None:
    em = _RecordingEmitter()
    args = Namespace(
        with_cli_tools=False,
        cli_tools_working_dir=".",
        memory_type="none",
        agent_store="sqlite",
        mcp_servers=[],
    )
    emit_control_plane_runtime_ready(em, args, harness_enabled=False)
    kw = em.ready_kw[-1]
    assert kw.get("harness_enabled") is False
    assert kw.get("agent_name") == "agloom-runtime"
    assert "cli_tools_enabled" in kw
