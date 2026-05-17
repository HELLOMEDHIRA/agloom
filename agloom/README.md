# agloom (Python package)

This directory is the **`agloom`** PyPI package: LangGraph-oriented agents, nine execution patterns, session memory, skills, feedback, and optional harness tooling.

## Install & docs

- **Install:** `pip install agloom` (optional extras: `agloom[groq]`, `agloom[openai]`, … — see `pyproject.toml`)
- **Documentation:** [agloom.readthedocs.io](https://agloom.readthedocs.io)
- **Repository:** [github.com/HELLOMEDHIRA/agloom](https://github.com/HELLOMEDHIRA/agloom)

## Two “doors” for developers

1. **Application API** — `from agloom import create_agent, UnifiedAgent`. This is what most users need: classify → pattern → tools/memory/streaming. Start at [Quick start](https://agloom.readthedocs.io/_packages/agloom/getting-started/quickstart/) and [Streaming & events](https://agloom.readthedocs.io/_packages/agloom/features/streaming/).

2. **Embedding API** — stable submodules for custom drivers and observability:
   - **`agloom.runtime`** — bridge one invocation to AGP (`run_invocation`), local `RuntimeNode`, workers, scheduler ([embedding guide](https://agloom.readthedocs.io/_packages/agloom/guides/embedding-runtime/))
   - **`agloom.protocol`** — typed AGP envelopes, emitters, command parsing, replay stores ([AGP from Python](https://agloom.readthedocs.io/_packages/agloom/guides/agp-python/), [wire spec](https://agloom.readthedocs.io/_packages/agloom/protocol/agp/))
   - **`agloom.observability`** — SQLite store + FastAPI router + SSE ([Observability API](https://agloom.readthedocs.io/_packages/agloom/guides/observability-python/))
   - **`agloom.llm`** — programmatic model resolution (`get_model`, env-key routing) ([LLM resolution](https://agloom.readthedocs.io/_packages/agloom/guides/llm-resolution/))

For **AGP-shaped streams inside Python** without NDJSON I/O, use **`UnifiedAgent.astream_agp_events()`** (same typed events as the runtime wire path).

## Repo layout note

Examples and tests under this tree ship in the **git** repo; the PyPI wheel contents are controlled by `pyproject.toml`. Browse runnable samples under `agloom/examples/` in GitHub.

The interactive terminal is the **agloom-cli** npm package (`agloom_cli/` in this repo), not the PyPI console script `agloom`. This wheel provides `create_agent`, `agloom-runtime`, and embedding APIs only.
