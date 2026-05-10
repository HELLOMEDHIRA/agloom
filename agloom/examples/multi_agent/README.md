# Multi-Agent

**`multi_agent.py`** — two `agloom` agents (`researcher` + `writer`) sharing the same
`InMemoryStore`, plus `abatch` for concurrent requests.

```bash
uv run multi_agent.py
```

Key concepts shown:
- Creating multiple agents with different `system_prompt` values
- Passing a shared `store=` so both agents read/write the same long-term memory namespace
- `agent.abatch(queries, max_concurrent=3)` for parallel inference
