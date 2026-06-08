# agloom Web Platform — Architecture

> Stack: React Router 7 · Vite 8 · TypeScript 6 · TailwindCSS 4 · Zustand 5 · React Flow · Monaco Editor

---

## 1. Guiding Principle

The web platform is an **AGP consumer**, exactly like the **agloom CLI**.  
Python never emits formatted HTML or UI hints — only structured AGP events over WebSocket.  
This guarantees AGP remains the single stable runtime abstraction across all frontend surfaces.

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             agloom ecosystem                                      │
│                                                                                   │
│  Python agent library              agloom-runtime (bridge process)              │
│  ┌─────────────────────┐          ┌──────────────────────────────────────────┐  │
│  │ Patterns · memory   │   AGP    │ Maps agent progress → wire events        │  │
│  │ Tools · streaming   │ ────────►│ serve --transport=ws  (this web app)   │  │
│  │ create_agent        │          │ serve --transport=stdio (CLI)            │  │
│  └─────────────────────┘          └──────────┬───────────────────────────────┘  │
│                                              │ typed JSON events                 │
│                 ┌────────────────────────────┼────────────────────────────┐      │
│                 │  agloom_cli (terminal)     │  agloom_web (browser)      │      │
│                 │  session store · HITL UI   │  same event vocabulary     │      │
│                 └────────────────────────────┴────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

| Concern       | Technology                  | Version | Reason                                          |
| ------------- | --------------------------- | ------- | ----------------------------------------------- |
| Routing       | **React Router**            | 7.15    | Vite-native SPA; user requirement (no Next.js)  |
| Build         | Vite                        | 8.0     | Fastest HMR; native ESM                         |
| Language      | TypeScript                  | 6.0     | Same baseline as agloom CLI; latest strict mode |
| Styling       | TailwindCSS 4               | 4.3     | Vite plugin; zero-config                        |
| State         | Zustand                     | 5.0     | Same store shape as agloom CLI; no boilerplate  |
| Data fetching | @tanstack/react-query       | 5.100   | REST calls (observability HTTP API, etc.)       |
| Graph viz     | @xyflow/react               | 12.10   | LangGraph node visualization                    |
| Code editor   | @monaco-editor/react        | 4.7     | Artifact viewer; full IDE editing future        |
| Charts        | recharts                    | 3.8     | Token/metric dashboards                         |
| Animation     | framer-motion               | 12.38   | Turn enter/exit, streaming transitions          |
| Markdown      | react-markdown + remark-gfm | 10 / 4  | Assistant response rendering                    |
| Icons         | lucide-react                | 1.14    | Consistent iconography                          |

---

## 3. Directory Structure

```text
agloom_web/
├── index.html                        # Vite entry
├── vite.config.ts                    # Vite + Tailwind + dev-proxy for AGP WS
├── tsconfig.json
├── package.json
└── src/
    ├── main.tsx                      # createRoot + BrowserRouter + QueryClient
    ├── App.tsx                       # Route declarations + AGPClient singleton
    ├── index.css                     # Tailwind base + dark theme tokens
    │
    ├── lib/
    │   ├── agp/
    │   │   ├── types.ts              # TypeScript mirror of AGP Pydantic models
    │   │   └── client.ts             # createAGPClient() (WebSocket) + React context
    │   ├── hooks/
    │   │   └── useAGPStream.ts       # Wire AGPClient events → Zustand dispatch
    │   └── utils/
    │       ├── cn.ts                 # cn(), fmtDuration(), fmtTokens()
    │       ├── assistantText.ts      # Final assistant text + token rollup display
    │       └── strayToolJson.ts      # Hide stray tool JSON in streamed assistant text
    │
    ├── store/
    │   └── session.ts                # Zustand store; reducer over AGP events
    │
    ├── routes/
    │   ├── WorkspaceHome.tsx         # /            — landing + new session
    │   ├── SessionWorkspace.tsx      # /session/:id — 3-panel workspace
    │   └── SettingsPage.tsx          # /settings    — runtime URL, model, etc.
    │
    └── components/
        ├── workspace/
        │   └── WorkspaceLayout.tsx   # Header + 3-panel shell
        ├── chat/
        │   ├── ChatPane.tsx          # Scroll container + empty state
        │   ├── CompletedTurnCard.tsx # Static completed turn (never re-renders)
        │   ├── StreamingTurn.tsx     # Live in-flight turn
        │   ├── HITLGate.tsx          # HITL approval prompt inline in chat
        │   └── ChatInput.tsx         # Textarea + send/cancel + token footer
        ├── runtime/
        │   ├── RuntimePanel.tsx      # Tab router (graph/workers/trace/artifacts)
        │   ├── RuntimeGraph.tsx      # React Flow graph from graph.node.* events
        │   ├── WorkerTree.tsx        # Worker + tool-call status tree
        │   └── ExecutionTrace.tsx    # Full AGP event log (terminal-style)
        └── artifacts/
            └── ArtifactViewer.tsx    # Monaco (code) + markdown + JSON viewer
```

---

## 4. AGP Communication

### Transport

During development Vite proxies `/agp-ws` → `ws://localhost:8765` so CORS never surfaces.  
In production set `VITE_AGP_WS_URL=wss://your-runtime.example.com`.

### Connection lifecycle

```text
App.tsx creates one client via createAGPClient() on mount → calls client.connect()
│
├─ WebSocket opens to runtime
├─ onStatus('open') → store.setConnectionStatus('open')
├─ onEvent(evt)     → store.dispatch(evt)        ← same reducer as agloom CLI
│
└─ on disconnect: auto-reconnect with 2 s backoff
```

### Sending commands

```typescript
// Invoke
client.invoke('What is agloom?', thread, session)

// Cancel
client.cancel(thread)

// HITL response
client.hitlRespond(requestId, 'accept')
```

---

## 5. State Architecture

The `useSessionStore` (Zustand) is the single source of truth.  
Its `dispatch(evt: AGPEvent)` function is a pure reducer — same architecture as the agloom CLI.

```text
AGP event received
      │
      ▼
store.dispatch(evt)
      │
      ├── appended to executionTrace (all events except token.delta)
      ├── matched on evt.type → exhaustive branches for every AGPKnownEvent
      │     session.* / agent.* / stream.* / runtime.*
      │     message.* / pattern / thinking / token.delta
      │     tool.call.* / worker.* / graph.node.*
      │     hitl.* / memory.* / checkpoint.* / feedback.*
      │     metric.tokens · metric.cost · skill.* · prompt.*
      │     error.*
      │     (+ protocolNotes for operational visibility — surfaced under the header in workspace)
      └── return next state (immutable)
```

### Display rules (parity with CLI)

- **Tool calls** — render full `tool.call.result` `output_preview` (wrap/scroll; no collapse toggle).
- **Reasoning** — `thinking.step` and plan/orchestration steps stay visible in the turn card.
- **Assistant text** — accumulate `token.delta`, then **`finalizeAssistantMessage`** when `message.assistant` arrives; strip `[agloom:tool_result]` envelopes and stray tool JSON blobs.
- **Tokens** — session totals from **`metric.tokens`** only; format as `↑input ↓output` via `formatTurnTokenRollup`.

---

## 6. Rendering Architecture

### Non-flickering pattern

`CompletedTurnCard` is wrapped in `React.memo` — it never re-renders after mount because completed turns are immutable.  
Only `StreamingTurn` re-renders on every `token.delta`, keeping React reconciliation work minimal.

### Three-panel layout

```text
┌──────── header bar (11px) ─────────────────────────────┐
│  agloom  ·  ● open  ·  [running]              ⚙  ⊞    │
├──────────────────────────────┬─────────────────────────┤
│                              │  [Graph|Workers|Trace|   │
│  chat pane (flex-1)          │   Files]  tab bar        │
│  ┌──────────────────────┐   │  ─────────────────────   │
│  │ CompletedTurnCard    │   │  RuntimeGraph            │
│  │ CompletedTurnCard    │   │  (React Flow)            │
│  │ StreamingTurn (live) │   │                           │
│  │ HITLGate (if hitl)   │   │                           │
│  └──────────────────────┘   │                           │
│  ─────── ChatInput ──────── │                           │
└──────────────────────────────┴─────────────────────────┘
```

---

## 7. Development

```bash
cd agloom_web
npm install
npm run dev           # → http://localhost:3000

# The Python runtime must be running separately:
# cd ..  &&  uv run python -m agloom.runtime serve --transport=ws --port 8765
```

**Tests:** `npm run test` runs Jest with **jsdom** — Zustand reducer coverage in `store.test.ts`, **`createAGPClient`** WebSocket behaviour (mock transport), **`useAGPClient`** context contract, and smoke tests for **`SettingsPage`** (environment copy) + **`ChatInput`**. Expand component coverage incrementally as panels stabilize.

---

## 8. Extension Points

The web platform is designed to remain an **AGP consumer**.  
New UI capabilities usually follow this flow:

1. Define or extend an **AGP event type** in the Python protocol (see [AGP specification](../agloom/protocol/agp.md))
2. Regenerate or sync TypeScript types for CLI and web clients
3. Handle the event in each client's **session store** reducer
4. Render with a new or existing panel component

Transport and `agloom-runtime` stay unchanged when the wire contract is backward compatible.

---

## 9. Deployment hardening

### `index.html` caching

Vite emits **content-hashed** JS/CSS under `dist/assets/`. Those files can be cached aggressively (`Cache-Control: immutable`).

**`index.html`** must **not** be cached for a long TTL: otherwise clients keep an old shell that references deleted chunks after deploy. Prefer **`Cache-Control: no-cache`** (revalidate) or a short `max-age` for `index.html` only.

### CSP / WebSocket

- **Browser:** If you use **Content-Security-Policy**, allow connect sources for your AGP endpoint, e.g. **`connect-src 'self' wss://your-runtime.example.com`** (adjust host/path).
- **Runtime:** Configure the Python WebSocket server for allowed **Origins** if it validates `Origin` (production setups often terminate TLS at a reverse proxy and forward WebSocket upgrades).

### Source maps

Production **`vite build`** uses **`build.sourcemap: 'hidden'`**: `.map` files are written for offline debugging but **not** linked from shipped JS, avoiding accidental exposure of raw sources to browsers.
