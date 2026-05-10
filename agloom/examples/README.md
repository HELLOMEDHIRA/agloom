# agloom Examples

Runnable Python examples organised by topic. Each subdirectory is self-contained — just set your `GROQ_API_KEY` and run.

```bash
export GROQ_API_KEY=gsk_...
uv run examples/quickstart/basic_agent.py
```

## Directories

| Directory | What it covers |
|---|---|
| [`quickstart/`](quickstart/) | Minimal `create_agent` + `ainvoke` — best starting point |
| [`tools/`](tools/) | Custom `@tool` functions, REACT pattern, step traces |
| [`streaming/`](streaming/) | `astream` (tokens) and `astream_events` (rich event stream) |
| [`patterns/`](patterns/) | Frozen agent — skip re-classification for batch workloads |
| [`multi_agent/`](multi_agent/) | Two agents sharing a `LongTermStore`, `abatch` concurrency |

## Prerequisites

```bash
pip install agloom langchain-groq
# or
uv add agloom langchain-groq
```
