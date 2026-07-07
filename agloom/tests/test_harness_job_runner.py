"""Harness job runner smoke."""

import pytest

from agloom.harness.job_runner import HarnessJobRunner


class _FakeResult:
    def __init__(self, success: bool, output: str = "ok"):
        self.success = success
        self.output = output
        self.metadata = {}


class _FakeAgent:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, _payload):
        self.calls += 1
        return _FakeResult(success=self.calls < 2)


@pytest.mark.asyncio
async def test_job_runner_commits_steps():
    runner = HarnessJobRunner(job_id="job-1", max_steps=5)
    agent = _FakeAgent()
    snap = await runner.run_until_blocked(agent, goal="investigate")
    assert snap.last_committed_step >= 1
    assert snap.status in ("completed", "failed")
