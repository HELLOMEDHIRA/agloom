"""Delegate work to a sub-agent via ``UnifiedAgent.adelegate`` (blocking until done)."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


def make_task_tools(agent_cell: list[Any | None]) -> list[Any]:
    """Return tools that call into the host ``UnifiedAgent`` after it is attached to *agent_cell*."""

    @tool
    async def task(prompt: str, delegate_name: str | None = None) -> str:
        """Run a sub-task on a **delegate** agent (see ``create_agent(..., delegates=[...])``).

        Blocks until the delegate finishes and returns its primary output text.
        Use *delegate_name* to pick a specific delegate; omit to use the first matching target.

        This uses the same routing as automatic handoffs — it does **not** start a fire-and-forget
        background job (see ``UnifiedAgent.adelegate_background`` for that).
        """
        agent = agent_cell[0] if agent_cell else None
        if agent is None:
            return "task: internal error — host agent not bound yet"
        q = (prompt or "").strip()
        if not q:
            return "task: empty prompt"
        try:
            result = await agent.adelegate(q, delegate_name=delegate_name)
            return result.output
        except ValueError as exc:
            return f"task: {exc}"
        except Exception as exc:
            return f"task: failed ({exc})"

    return [task]
