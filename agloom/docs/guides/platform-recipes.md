# Platform embedded recipes

## rca-platform (minimal)

```python
agent = await create_agent(
    model=llm,
    store=store,
    profile="platform_embedded",
    harness_metadata=HarnessMetadata(project_name=investigation_id, goal=goal),
)
```

Optional autonomous loop:

```python
from agloom.harness.job_runner import HarnessJobRunner

runner = HarnessJobRunner(job_id=investigation_id)
snap = await runner.run_until_blocked(agent, goal=goal)
```

Persist `snap.last_committed_step` and `ExecutionResult.failure_class` on your investigation row.
