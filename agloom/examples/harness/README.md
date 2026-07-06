# Harness example

Long-running **harness** with in-memory LangGraph store — turn planner may seed a durable task ledger across turns.

```bash
export GROQ_API_KEY=gsk_...
uv run python agloom/examples/harness/harness_agent.py
```

Requires `langchain-groq`. See [Long-running harness](../../docs/features/harness.md).
