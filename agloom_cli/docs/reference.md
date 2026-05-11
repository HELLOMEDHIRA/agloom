# AGP wire reference (CLI clients)

This page is for **anyone driving `agloom-runtime` over stdio** (the npm CLI, custom scripts, or another terminal UI). End-user documentation starts at [Overview](index.md).

## Legacy shell

The old Python Typer/Rich REPL has been **removed**. Use the **`agloom-cli`** package plus **`agloom-runtime`**.

## AGP stream contract

- **`stdout`** from `agloom-runtime` is **AGP NDJSON only** — one JSON object per line. Each object follows the [AGP specification](../agloom/protocol/agp.md) (`type`, envelope fields, `data`).
- **Diagnostics** (warnings, hints, startup banners from Python) go to **`stderr`**. Parsers must **not** treat stderr as part of the protocol stream.

**Parsing:** Read stdout line-by-line; parse each non-empty line as JSON and dispatch on `type`. Do not scrape stderr for machine-readable AGP events.

## Related docs

- [AGP specification](../agloom/protocol/agp.md) — canonical event types and shapes
- [Runtime architecture](../agloom/runtime/architecture.md)
- [Package README](https://github.com/HELLOMEDHIRA/agloom/blob/main/agloom_cli/README.md)

**Maintainers:** workflow for the npm CLI bridge (layout, tests, adding event types) lives in [**`CONTRIBUTING.md`**](https://github.com/HELLOMEDHIRA/agloom/blob/main/CONTRIBUTING.md) at the repository root (not duplicated here).
