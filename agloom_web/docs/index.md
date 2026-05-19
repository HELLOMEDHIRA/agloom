# Web workspace (`agloom_web`)

Browser workspace for agloom agents — same **AGP** event vocabulary as the terminal CLI, delivered over **WebSocket**.

## Quick start

```bash
# Terminal 1 — Python bridge
agloom-runtime serve --transport=ws --port 8765

# Terminal 2 — web dev server
cd agloom_web && npm install && npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Vite proxies **`/agp-ws`** → `ws://localhost:8765` in development.

Production: **`npm run build`** → serve **`dist/`** with **`VITE_AGP_WS_URL=wss://your-runtime.example.com`** at build time (see **`.env.example`**).

---

## What you get

| Surface | Purpose |
| ------- | ------- |
| **Chat** | Streaming assistant, full tool rows, inline HITL |
| **Runtime panel** | Graph, workers, execution trace, artifacts |
| **Observability** | `/observe` dashboard and per-session replay |

The web app is an **AGP consumer** — it does not run Python in the browser.

---

## Routes

| Path | Screen |
| ---- | ------ |
| **`/`** | Home — sessions / navigation |
| **`/session/:id`** | Chat + runtime sidebar |
| **`/observe`** | Live metrics and sessions |
| **`/sessions/:id/trace`** | Trace viewer & replay |
| **`/settings`** | Connection hints |

---

## Documentation

| Page | Content |
| ---- | ------- |
| [architecture.md](architecture.md) | Stack, state reducer, display rules, deployment |
| [AGP protocol](../agloom/protocol/agp.md) | Wire contract (MkDocs **Protocol**) |
| [Production deployment](../agloom/guides/deployment.md) | Docker, reverse proxy, `VITE_AGP_WS_URL` |

---

## Parity with the CLI

Both clients:

- Dispatch AGP events through a **Zustand `dispatch` reducer**
- Prefer **`message.assistant`** for final text (not raw tool JSON)
- Show **full** tool results and reasoning traces
- Roll up tokens from **`metric.tokens`** (`↑` / `↓` display)

Differences: CLI uses **stdio**; web uses **WebSocket** + optional **`/observe`** HTTP in dev.
