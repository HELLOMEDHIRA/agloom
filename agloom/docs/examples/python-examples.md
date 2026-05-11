# Python examples (in-tree)

Runnable examples live under **`agloom/examples/`** in the repository (they are **not** shipped in the PyPI wheel).

| Topic | Path |
| --- | --- |
| Minimal agent | `agloom/examples/quickstart/basic_agent.py` |
| Tools & ReAct | `agloom/examples/tools/tools_and_react.py` |
| Streaming | `agloom/examples/streaming/streaming.py` |
| Frozen / batch-style agent | `agloom/examples/patterns/frozen_agent.py` |
| Multi-agent | `agloom/examples/multi_agent/multi_agent.py` |

Each subdirectory has a short `README.md`. From the repo root::

```bash
uv sync --group dev
uv run python agloom/examples/quickstart/basic_agent.py
```
