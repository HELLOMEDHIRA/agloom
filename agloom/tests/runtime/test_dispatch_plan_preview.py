"""``command.plan.preview`` must not touch ``agent.config`` before bootstrap."""

from __future__ import annotations

import asyncio
import io

import pytest

from agloom.protocol import SessionEmitter
from agloom.protocol.commands import CommandPlanPreview, CommandPlanPreviewData
from agloom.runtime.command_dispatch import dispatch_command
from agloom.runtime.hitl import HITLBridge


class _PlanPreviewEmitter(SessionEmitter):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(session="s_plan", thread="t_plan", writer=io.StringIO())
        self._errors = errors

    def emit_error(self, *, message: str, **kw: object) -> object:
        self._errors.append(message)
        return super().emit_error(message=message, **kw)


@pytest.mark.asyncio
async def test_plan_preview_without_agent_does_not_raise() -> None:
    errors: list[str] = []
    emitter = _PlanPreviewEmitter(errors)
    hitl_bridge = HITLBridge(emitter, tool_allowlist=set())
    await dispatch_command(
        CommandPlanPreview(data=CommandPlanPreviewData(prompt="ship feature X")),
        agent=None,
        emitter=emitter,
        hitl_bridge=hitl_bridge,
        ensure_agent=None,
        invocation_tasks=set(),
        thread_tasks={},
        shutdown=asyncio.Event(),
    )

    assert errors
