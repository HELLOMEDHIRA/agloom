# agloom Examples

Runnable Python examples organised by topic. Most examples need a Groq API key; start with **`smoke/`** if you only want to verify the install.

```bash
# No API key — import + version check
uv run examples/smoke/smoke_imports.py

# Groq-backed quickstart
export GROQ_API_KEY=gsk_...
uv run examples/quickstart/basic_agent.py

# Multi-session harness (task ledger across turns)
uv run examples/harness/harness_agent.py
```

## Recommended paths

| Goal | Start here |
| --- | --- |
| First agent | [`quickstart/basic_agent.py`](quickstart/basic_agent.py) |
| Multi-session coding / RCA | [`harness/harness_agent.py`](harness/harness_agent.py) |
| Tools & ReAct | [`tools/tools_and_react.py`](tools/tools_and_react.py) |
| Streaming UI | [`streaming/streaming.py`](streaming/streaming.py) |

## Directories

| Directory | What it covers |
| --- | --- |
| [`smoke/`](smoke/) | Import + version check — **no API key** |
| [`quickstart/`](quickstart/) | Minimal `create_agent` + `ainvoke` — best starting point |
| [`harness/`](harness/) | **Long-running harness** + `HarnessMetadata` across turns |
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

Docs: [Python examples](../docs/examples/python-examples.md) · [Long-running harness](../docs/features/harness.md) · [Use cases](../docs/guides/use-cases.md)
