# Python examples (in-tree)

Runnable scripts live under **`agloom/examples/`** in the GitHub repository. They are **not** included in the PyPI wheel — clone the repo or browse on GitHub.

## What each example teaches

| Example | Path | You will learn |
| ------- | ---- | -------------- |
| **Minimal agent** | `agloom/examples/quickstart/basic_agent.py` | `create_agent`, `ainvoke`, first result |
| **Tools & ReAct** | `agloom/examples/tools/tools_and_react.py` | `@tool`, automatic tool loop |
| **Streaming** | `agloom/examples/streaming/streaming.py` | `astream_events` for UIs |
| **Frozen / batch agent** | `agloom/examples/patterns/frozen_agent.py` | Fixed pattern bias, batch-style calls |
| **Multi-agent** | `agloom/examples/multi_agent/multi_agent.py` | Supervisor-style workloads |

Each folder has a short **README** with prerequisites (API keys, extras).

## Run from a clone

```bash
uv sync --group dev
export GROQ_API_KEY=your_key   # or OPENAI_API_KEY, etc.
uv run python agloom/examples/quickstart/basic_agent.py
```

Install only the extras you need, e.g. `pip install 'agloom[groq]'`.

## Prefer docs-first?

- [Quickstart](../getting-started/quickstart.md) — install + first agent in one page
- [Create an agent](../concepts/create-agent.md) — full `create_agent` surface
- [Production integration](../guides/production.md) — FastAPI, persistence, tenants

## Web and CLI

- **CLI:** [agloom CLI docs](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/)
- **Web workspace:** [agloom_web architecture](https://agloom.readthedocs.io/en/latest/_packages/agloom_web/architecture/)
