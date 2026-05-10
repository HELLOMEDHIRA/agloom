# CLI developer reference

Notes for contributors maintaining **agloom-cli** or another AGP client talking to `agloom-runtime`. End-user install and flags are on the [quick start](index.md).

## Legacy shell

The old Python Typer/Rich REPL has been **removed**. Use **`agloom_cli/`** (this package) plus **`agloom-runtime`**.

## AGP stream contract

- **`stdout`** from `agloom-runtime` is **AGP NDJSON only** — one JSON object per line.
- **Diagnostics** (warnings, banners, provider hints) go to **`stderr`** so parsers keep `stdout` clean.

Consumers should use **typed AGP events** (`src/types/agp.ts`), not ad hoc log scraping.

## Architecture (this repo)

| Area | Role |
|------|------|
| `src/runtime/bridge.ts` | `createAGPBridge()` — spawns `agloom-runtime`, parses NDJSON, typed `on`/`emit` via internal `EventEmitter`. |
| `src/store/session.ts` | Single zustand reducer: **`dispatch(AGPEvent)`** updates UI state + **Wire notes**. |
| `src/hooks/useAGPStream.tsx` | Subscribes the bridge to the store (strict-mode safe). |
| `src/components/*` | Ink UI; slash commands are handled in `App.tsx`. |

### Adding a new inbound event type

1. Mirror the Python model in **`src/types/agp.ts`** (and keep **`agloom_web`** copy identical).
2. Handle it in **`session.ts`** → `dispatch` switch (update structured state and/or **`protocolNotes`**).
3. Add a **jest** case in **`src/__tests__/store.test.ts`** for the reducer branch.

### Tests

- **`npm test`** — `bridge.test.ts` (serialization, NDJSON framing) + `store.test.ts` (reducers).
- Ink components are not rendered in CI; exercise logic via the store where possible.

### Build

```bash
npm run build    # tsc → dist/
npm run lint
npm run typecheck
```

## TypeScript / EventEmitter

The bridge is a **factory** (`createAGPBridge`) that wraps Node’s `EventEmitter` internally; the public type is `AGPBridge` (interface with typed `on` / `once` / `off` / `emit`).

## Related docs

- [AGP specification](../agloom/protocol/agp.md)
- [Runtime architecture](../agloom/runtime/architecture.md)
- [Package README](https://github.com/HELLOMEDHIRA/agloom/blob/main/agloom_cli/README.md) — slash commands, exit codes, env vars
