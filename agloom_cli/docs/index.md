# agloom CLI — quick start

The **agloom CLI** is the Node.js package in `agloom_cli/` (npm **`agloom-cli`**). It implements the terminal UI with **Ink** and **React**, and streams **AGP** (newline-delimited JSON) over stdio to **`agloom-runtime`**.

## Prerequisites

- Python **3.12.x** with `agloom` installed (library + `agloom-runtime` console script).
- **Node.js >=24.15.0** to build and run this package (same requirement as `agloom_web/`).

## Install from source

```bash
git clone https://github.com/HELLOMEDHIRA/agloom.git
cd agloom
uv sync --all-extras --group dev    # Python deps

cd agloom_cli
npm install
npm run build
npm start                           # or: node dist/index.js
```

By default the CLI spawns:

    agloom-runtime serve --transport=stdio

Runtime flags (`--thread`, `--session`, `--store`, …) are wired from `agloom_cli/package.json` / `agloom_cli/src/index.tsx`.

## PyPI `agloom` console script

| Command | Role |
| --------|------|
| `agloom-runtime` | AGP bridge — stdio or WebSocket (`serve --transport=…`). |
| `agloom` | **Compatibility**: short notice that the agloom CLI lives under `agloom_cli/`; avoids stale bookmarks hitting an empty entrypoint. |

## Using agloom without this CLI

You do **not** need the agloom CLI for the Python library:

```python
from agloom import create_agent

agent = create_agent(model="openai:gpt-4o", tools=[...])
result = await agent.ainvoke("Hello")
```

Custom frontends should use `agent.astream_events(...)` or AGP-oriented APIs as needed.

## Next steps

- [AGP specification](../agloom/protocol/agp.md)
- [Runtime architecture](../agloom/runtime/architecture.md)
- [CLI developer reference](reference.md) — stdout/stderr rules and AGP consumption for authors
