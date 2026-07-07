"""Optional harness job runner for long-running embedded investigations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_STEP_NS = ("harness", "steps")


@dataclass
class JobSnapshot:
    job_id: str
    last_committed_step: int = 0
    last_committed_turn: int = 0
    status: str = "pending"
    failure_class: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HarnessJobRunner:
    """Drive repeated harness micro-turns until blocked or complete."""

    def __init__(
        self,
        *,
        job_id: str,
        max_steps: int = 10_000,
        store: Any = None,
    ) -> None:
        self.job_id = job_id
        self.max_steps = max_steps
        self._store = store
        self._step_log: list[dict[str, Any]] = []

    @property
    def step_log(self) -> list[dict[str, Any]]:
        return list(self._step_log)

    def _step_key(self) -> str:
        return self.job_id

    async def _load_from_store(self) -> None:
        store = self._store
        if store is None:
            return
        try:
            item = await store.aget(_STEP_NS, self._step_key())
            if item and isinstance(item.value, dict):
                self._step_log = list(item.value.get("steps", []))
        except Exception:
            return

    async def _persist_steps(self) -> None:
        store = self._store
        if store is None:
            return
        try:
            await store.aput(
                _STEP_NS,
                self._step_key(),
                {"job_id": self.job_id, "steps": self._step_log},
            )
        except Exception:
            return

    async def commit_step(self, *, digest: str, outcome: str, refs: list[str] | None = None) -> int:
        step_idx = len(self._step_log)
        self._step_log.append(
            {
                "step_id": step_idx,
                "digest": digest,
                "outcome": outcome,
                "artifact_refs": refs or [],
            }
        )
        await self._persist_steps()
        return step_idx

    async def run_until_blocked(self, agent: Any, *, goal: str, max_steps: int | None = None) -> JobSnapshot:
        await self._load_from_store()
        limit = max_steps if max_steps is not None else self.max_steps
        turn = self._step_log[-1]["step_id"] + 1 if self._step_log else 0
        while turn < limit:
            turn += 1
            result = await agent.ainvoke({"messages": [{"role": "user", "content": goal}]})
            await self.commit_step(
                digest=str(result.output)[:500],
                outcome="ok" if result.success else "failed",
            )
            if not result.success:
                return JobSnapshot(
                    job_id=self.job_id,
                    last_committed_step=len(self._step_log),
                    last_committed_turn=turn,
                    status="failed",
                    failure_class=getattr(result, "failure_class", None),
                    metadata=dict(result.metadata or {}),
                )
        return JobSnapshot(
            job_id=self.job_id,
            last_committed_step=len(self._step_log),
            last_committed_turn=turn,
            status="completed",
        )

    async def resume(self, agent: Any, *, from_step: int | None = None, goal: str = "") -> JobSnapshot:
        await self._load_from_store()
        start = from_step if from_step is not None else len(self._step_log)
        self._step_log = self._step_log[:start]
        await self._persist_steps()
        if goal:
            return await self.run_until_blocked(agent, goal=goal)
        return JobSnapshot(
            job_id=self.job_id,
            last_committed_step=start,
            status="paused",
        )
