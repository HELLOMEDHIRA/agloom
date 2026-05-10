# agloom-cli

**agloom** terminal client — **Ink** + **React** UI over the **AGP** stream (NDJSON on stdio) talking to **`agloom-runtime`** from the PyPI `agloom` package.

## Prerequisites (read this first)

1. **Python:** install the library so the `agloom-runtime` script exists:

   ```bash
   pip install agloom
   ```

   Without this step, the CLI exits with a clear **ENOENT** hint (`pip install agloom` or `AGLOOM_RUNTIME`).

2. **Node.js:** **>= 24.15** (see `package.json` → `engines`; aligns with `agloom_web`).

## Install (npm)

```bash
npm install -g agloom-cli
agloom
```

From a git checkout, run `npm install && npm run build`, then `npm start` or `node dist/index.js`.

## Runtime binary & env

| Override | Meaning |
|----------|---------|
| *(default)* | Looks up `agloom-runtime` on `PATH` (from `pip install agloom`). |
| `AGLOOM_RUNTIME` | Full path to the interpreter or script that should run the runtime (advanced). |

This package only drives the child over **stdio** (`serve --transport=stdio`). It does **not** embed a WebSocket client for `serve --transport=ws`.

## CLI flags (parsed by `agloom`, forwarded to `agloom-runtime` where noted)

| Flag | Purpose |
|------|---------|
| `-t, --thread <id>` | LangGraph thread id used for `command.invoke` (default: minted id). |
| `-s, --session <id>` | Passed through as **`agloom-runtime --session`** so the Python emitter uses that session id (replay / stable id). |
| `--store <none\|memory\|sqlite>` | Event store backend for the runtime (default `memory`). |
| `--store-path <path>` | SQLite path when `--store=sqlite`. |
| `--diag` | Open the **stderr diagnostic** pane on startup (`/diag` toggles it anytime). |
| `-- …` | Extra tokens after `--` are appended to the runtime argv (pass-through). |

**Unknown flags:** Commander uses `.allowUnknownOption()` so arguments after `--` can reach `agloom-runtime`. Typos on **declared** flags still fail validation.

Everything after a lone **`--`** is appended to the **`agloom-runtime serve`** argv. Use this for flags the npm CLI does not wrap (`--with-cli-tools`, `--obs`, `--hitl-allowlist-path`, WebSocket tuning, etc.) without maintaining duplicate parsers in Node.

## Slash commands (inside the UI)

| Command | Action |
|---------|--------|
| `/help` | Toggle full command list (Esc or **q** to close). |
| `/cancel` | Cancel current run (same as **Ctrl+X**). |
| `/clear` | Clear transcript and sidebar wire notes. |
| `/model` | Append active model + tool count to **Wire notes**. |
| `/diag` | Toggle Python **stderr** log pane. |
| `/stats` | Toggle right-hand **metrics** sidebar. |
| `/feedback <1-5> [text]` | Send feedback for the last completed turn. |
| `/exit`, `/quit` | Shutdown runtime and exit. |

Many AGP responses (`runtime.config`, `feedback.scored`, memory, skills, …) append one-line entries under **Wire notes** in the metrics sidebar.

## Exit codes

| Situation | Code |
|-----------|------|
| Normal quit (`/exit`, Ctrl+C after shutdown) | **0** |
| Bridge spawn error (e.g. missing `agloom-runtime`) | **1** |
| Python process exited non-zero | Child **exit code** |
| Killed by signal (other than SIGTERM during shutdown) | **1** |

## Documentation

- **Quick start & flags:** [docs/index.md](docs/index.md)
- **Contributor reference:** [docs/reference.md](docs/reference.md)
- **AGP wire format:** [Python package protocol doc](https://agloom.readthedocs.io/_packages/agloom/protocol/agp/) (repo: `agloom/docs/protocol/agp.md`)
- **Runtime:** [Runtime architecture](https://agloom.readthedocs.io/_packages/agloom/runtime/architecture/)

## Development

```bash
cd agloom_cli
npm install
npm run build      # tsc → dist/
npm run lint
npm test           # jest (bridge + store)
npm run dev        # tsx src/index.tsx
```

AGP TypeScript types live in **`src/types/agp.ts`** — keep in sync with **`agloom_web/src/lib/agp/types.ts`**.

## Repo

[github.com/HELLOMEDHIRA/agloom](https://github.com/HELLOMEDHIRA/agloom) — package path **`agloom_cli/`**.
