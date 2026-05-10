# agloom CLI — quick start

The **agloom CLI** is the Node.js package in `agloom_cli/` (npm **`agloom-cli`**). It implements the terminal UI with **Ink** and **React**, and streams **AGP** (newline-delimited JSON) over stdio to **`agloom-runtime`**.

## Prerequisites

- **Python 3.12+** with **`pip install agloom`** so `agloom-runtime` exists on `PATH`.
- **Node.js >= 24.15** to build and run this package (`engines` in `package.json`, same baseline as `agloom_web`).

!!! warning "npm alone is not enough"
    `npm install -g agloom-cli` without the Python package produces a helpful **Cannot find agloom-runtime** error. Install **`agloom`** from PyPI first.

## Install from npm

```bash
pip install agloom
npm install -g agloom-cli
agloom
```

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

```text
agloom-runtime serve --transport=stdio …
```

Only **stdio** is supported from this client (no embedded WebSocket driver).

## CLI flags

Declared in `agloom_cli/src/index.tsx`:

| Flag | Description |
|------|-------------|
| `-t, --thread <id>` | LangGraph thread id for invocations (default: generated). |
| `-s, --session <id>` | Forwarded as **`agloom-runtime --session`** (stable AGP session id / replay key). |
| `--store <none\|memory\|sqlite>` | Runtime EventStore backend (default `memory`). |
| `--store-path <path>` | SQLite path when `--store=sqlite`. |
| `--diag` | Open stderr diagnostic pane on start. |
| `-- …` | Everything after `--` is appended to the runtime argv. |

**Pass-through:** Use this to forward native `agloom-runtime serve` flags without the npm CLI declaring each one. Examples:

```bash
agloom -- --with-cli-tools --cli-tools-working-dir /path/to/repo
agloom --session dev -- --obs --obs-port 8766
```

See the [Runtime CLI reference](https://agloom.readthedocs.io/_packages/agloom/runtime/cli/) for the full flag list.

**Slash commands** inside the UI (`/help`, `/cancel`, `/diag`, …) are listed in the [package README](https://github.com/HELLOMEDHIRA/agloom/blob/main/agloom_cli/README.md) and toggled with **`/help`**.

**Environment:** `AGLOOM_RUNTIME` overrides the executable path for the Python bridge.

## PyPI `agloom` console script

| Command | Role |
| --------|------|
| `agloom-runtime` | AGP bridge — stdio or WebSocket (`serve --transport=…`). |
| `agloom` | Compatibility notice pointing integrators at this npm CLI. |

## Using agloom without this CLI

You do **not** need the agloom CLI for the Python library:

```python
from agloom import create_agent

agent = await create_agent(model="openai:gpt-4o", tools=[...])
result = await agent.ainvoke("Hello")
```

Custom frontends should use `agent.astream_events(...)` or AGP-oriented APIs as needed.

## Next steps

- [AGP specification](../agloom/protocol/agp.md)
- [Runtime architecture](../agloom/runtime/architecture.md)
- [CLI developer reference](reference.md) — stdout/stderr, store reducers, contributing
