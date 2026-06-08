# Patterns

**`frozen_agent.py`** — demonstrates the `frozen=True` flag that locks the
pattern after the first classification, saving ~200–500 ms per call.

```bash
uv run frozen_agent.py
```

Ideal for batch or template-driven workloads (translation, extraction, summarisation)
where the prompt structure is fixed and only the input data changes.
