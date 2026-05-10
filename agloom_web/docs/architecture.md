# agloom Web Platform — Architecture

> Status: **Phase 1 implementation complete**
> Stack: React Router 7 · Vite 8 · TypeScript 6 · TailwindCSS 4 · Zustand 5 · React Flow · Monaco Editor

---

## 1. Guiding Principle

The web platform is an **AGP consumer**, exactly like the **agloom CLI**.  
Python never emits formatted HTML or UI hints — only structured AGP events over WebSocket.  
This guarantees AGP remains the single stable runtime abstraction across all frontend surfaces.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             agloom ecosystem                                      │
│                                                                                   │
│  agloom-core (Python)          agloom-runtime (Python)                            │
│  ┌─────────────────────┐      ┌──────────────────────────────────────────────┐   │
│  │ LangGraph workflows │  AGP │ RuntimeNode · WorkerPool · Scheduler         │   │
│  │ Memory / tools      │──────│ serve --transport=ws  (WebSocket)            │   │
│  │ UnifiedAgent        │      │ serve --transport=stdio (agloom CLI)        │   │
│  └─────────────────────┘      └──────────┬───────────────────────────────────┘   │
│                                          │ AGP (Envelopes over WS / stdio)        │
│                 ┌────────────────────────┼────────────────────────────────┐       │
│                 │                        │                                │       │
│      agloom_cli (agloom CLI)    agloom_web (React Router)          future:   │      │
│         AGPBridge (stdio)       AGPClient (WebSocket)            VSCode ext│      │
│         Zustand store           Zustand store                    dashboards│      │
│                 │                        │                                │       │
│                 └────────────────────────┴────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

| Concern                | Technology                  | Version  | Reason                                           |
| ---------------------- | --------------------------- | -------- | ------------------------------------------------ |
| Routing                | **React Router**            | 7.15     | Vite-native SPA; user requirement (no Next.js)   |
| Build                  | Vite                        | 8.0      | Fastest HMR; native ESM                          |
| Language               | TypeScript                  | 6.0      | Same baseline as agloom CLI; latest strict mode   |
| Styling                | TailwindCSS 4               | 4.3      | Vite plugin; zero-config                         |
| State                  | Zustand                     | 5.0      | Same store shape as agloom CLI; no boilerplate    |
| Data fetching          | @tanstack/react-query       | 5.100    | REST calls (settings, session list, etc.)        |
| Graph viz              | @xyflow/react               | 12.10    | LangGraph node visualization                     |
| Code editor            | @monaco-editor/react        | 4.7      | Artifact viewer; full IDE editing future         |
| Charts                 | recharts                    | 3.8      | Token/metric dashboards                          |
| Animation              | framer-motion               | 12.38    | Turn enter/exit, streaming transitions           |
| Markdown               | react-markdown + remark-gfm | 10 / 4   | Assistant response rendering                     |
| Icons                  | lucide-react                | 1.14     | Consistent iconography                           |

---

## 3. Directory Structure

```
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
    │   │   └── client.ts             # AGPClient (WebSocket) + React context
    │   ├── hooks/
    │   │   └── useAGPStream.ts       # Wire AGPClient events → Zustand dispatch
    │   └── utils/
    │       └── cn.ts                 # cn(), truncate(), fmtDuration(), fmtTokens()
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

```
App.tsx creates one AGPClient on mount → calls client.connect()
│
├─ AGPClient opens WebSocket
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

```
AGP event received
      │
      ▼
store.dispatch(evt)
      │
      ├── appended to executionTrace (all events except token.delta)
      ├── matched on evt.type →
      │     session.opened      → set sessionId, runtimeVersion
      │     message.user        → create activeTurn
      │     token.delta         → activeTurn.streamedTokens += token
      │     tool.call/result    → upsert into activeTurn.toolCalls
      │     worker.*            → upsert into activeTurn.workers
      │     graph.node.*        → upsert into activeTurn.graphNodes
      │     hitl.request        → push to hitlQueue, status='hitl'
      │     message.assistant   → promote activeTurn → completedTurn
      │                            extract code/markdown artifacts
      │     metric.tokens       → totalInputTokens / totalOutputTokens
      │     error.*             → errorMessage, status
      └── return next state (immutable)
```

---

## 6. Rendering Architecture

### Non-flickering pattern

`CompletedTurnCard` is wrapped in `React.memo` — it never re-renders after mount because completed turns are immutable.  
Only `StreamingTurn` re-renders on every `token.delta`, keeping React reconciliation work minimal.

### Three-panel layout

```
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

---

## 8. Phased Roadmap

| Phase | Scope |
| ----- | ----- |
| **1 (now)** | Core workspace: chat, streaming, HITL, React Flow graph, worker tree, execution trace, artifact viewer |
| **2** | Session persistence sidebar; session list; resume from checkpoint via `session.resumed` AGP event |
| **3** | Token / latency charts (recharts); cost dashboard; model comparison |
| **4** | Workflow builder (React Flow editable graph → `command.invoke` with graph spec) |
| **5** | Multi-runtime view: connect to multiple `agloom-runtime` instances simultaneously |
| **6** | Collaborative workspaces; real-time multi-user cursors (via presence channel on AGP) |
| **7** | agloom Cloud integration; deployment management; remote runtime provisioning |

---

## 9. Extension Points

The web platform is designed to remain an **AGP consumer** through all phases.  
New capabilities are added by:

1. Adding AGP event types in `agloom/protocol/events.py`
2. Mirroring them in `agloom_cli/src/types/agp.ts` and `agloom_web/src/lib/agp/types.ts` (the two files must stay identical)
3. Adding a `case` in `store/session.ts`'s `dispatch` reducer
4. Adding a new component or extending an existing panel

No changes to AGP transport, WebSocket server, or Python runtime are needed.
