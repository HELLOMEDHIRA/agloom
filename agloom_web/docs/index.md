# Web workspace (`agloom_web`)

Vite + React Router SPA that consumes **AGP** over WebSocket — same event contract as **agloom-cli** (stdio bridge).

## Quick start

1. `cd agloom_web && npm install && npm run dev`
2. Run **`agloom-runtime serve --transport=ws`** (default port **8765** matches the Vite proxy for `/agp-ws`).
3. Open **http://localhost:3000**.

Production build: **`npm run build`** → static **`dist/`**. Set **`VITE_AGP_WS_URL`** at build time for your runtime WebSocket URL (see **`.env.example`**).

## Routes (Phase 1)

| Path | Screen |
| ---- | ------ |
| **`/`** | Home — sessions list / navigation |
| **`/session/:id`** | Chat + right-hand runtime panel (graph, workers, trace, artifacts) |
| **`/observe`** | Observability dashboard (live metrics / sessions; uses proxied **`/observe`** HTTP in dev) |
| **`/sessions/:id/trace`** | Per-session trace & replay |
| **`/settings`** | Runtime connection hints (WS URL is primarily **`VITE_AGP_WS_URL`**) |

## Documentation

- **[architecture.md](architecture.md)** — stack, proxies, state (`dispatch` reducer parity with CLI), deployment & CSP notes.
- **Python / AGP protocol** — canonical spec in the main repo at `agloom/docs/protocol/agp.md` (published under MkDocs **Protocol**).

The Zustand **`dispatch`** reducer handles **every** inbound **`AGPEvent`** type so wire traffic is not silently dropped; runtime/tool/memory feedback surfaces via **`protocolNotes`** and the execution trace panel.
