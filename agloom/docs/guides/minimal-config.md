# Minimal config guide

Integrators pass only what they must:

```python
from agloom import create_agent

agent = await create_agent(
    model=llm,
    store=store,
    profile="interactive",
)
```

For RCA / long harness jobs:

```python
agent = await create_agent(
    model=llm,
    store=store,
    profile="platform_embedded",
    harness_metadata=HarnessMetadata(project_name="...", goal="..."),
)
```

Context management (summarization, scratchpad, recall) is automatic.
