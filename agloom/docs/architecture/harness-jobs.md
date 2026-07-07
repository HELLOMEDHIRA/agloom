# Harness jobs

Long-running investigations use optional `HarnessJobRunner`:

```python
from agloom.harness import HarnessJobRunner

runner = HarnessJobRunner(job_id=investigation_id)
snap = await runner.run_until_blocked(agent, goal=goal)
await runner.resume(agent, from_step=snap.last_committed_step)
```

Step commits are append-only in the runner; persist `last_committed_step` in your platform store.
