# CLI developer reference

Notes for contributors maintaining the **agloom CLI** or another AGP client talking to `agloom-runtime`. **Install and first run** are on the [quick start](index.md); this page does not repeat them.

## Legacy shell

The old Python Typer/Rich REPL from legacy docs has been **removed**. Use **`agloom_cli/`** (agloom CLI) plus **`agloom-runtime`**.

## AGP stream contract

- **`stdout`** from `agloom-runtime` is reserved for **AGP NDJSON envelopes only** — one JSON object per line, machine-oriented.
- **Human-readable diagnostics** (warnings, banners, provider hints) must go to **`stderr`** so parsers can treat `stdout` as a clean event stream.

Consumers (**agloom CLI**, web workspace, observability tooling) should rely on **typed AGP events** (see the protocol doc), not ad‑hoc log-line scraping.

## Related docs

- [AGP specification](../agloom/protocol/agp.md)
- [Runtime architecture](../agloom/runtime/architecture.md)
