# agloom-web

**Deployable SPA** (not an npm library): React Router + Vite workspace for AGP-native sessions — chat, observability dashboards, runtime visualization, session trace replay.

`package.json` sets **`"private": true`** so this app is never published to npm; release artifacts are static files under `dist/` after `npm run build`.

## Features & routes

| Route | Purpose |
| ----- | ------- |
| `/` | Workspace home — open or start sessions |
| `/session/:sessionId` | Three-panel workspace (chat + runtime tabs) |
| `/observe` | Observability dashboard (HTTP `/observe` API in dev) |
| `/sessions/:sessionId/trace` | Session trace / replay |
| `/settings` | Runtime URL and UI preferences |

## Configuration

- **`VITE_AGP_WS_URL`** — WebSocket URL for `createAGPClient()` (see `src/App.tsx`). If unset, defaults to **`/agp-ws`**, which Vite proxies to `ws://localhost:8765` in development. For production, set e.g. `wss://your-host/agp` or your reverse-proxy path.
- Copy **`.env.example`** to **`.env.local`** and adjust.

## Development

From **`agloom_web/`**:

```bash
npm install
npm run dev          # http://localhost:3000
```

Run the Python runtime separately, e.g. `agloom-runtime serve --transport=ws` (port **8765** matches the default dev proxy).

```bash
npm run build        # output: dist/
npm run preview      # serve dist locally
```

## Deployment

1. Set **`VITE_AGP_WS_URL`** at build time so the client opens the correct `wss:` endpoint.
2. Serve **`dist/`** as static assets; configure the host so **`index.html`** is not long-cached (see `docs/architecture.md` — caching appendix).
3. Terminate TLS at your edge; WebSocket upgrade must reach the AGP runtime.

AGP TypeScript types live in **`src/lib/agp/types.ts`** — keep them identical to **`agloom_cli/src/types/agp.ts`**.

- **Repo:** [github.com/HELLOMEDHIRA/agloom](https://github.com/HELLOMEDHIRA/agloom) · tree path `agloom_web/`
- **Docs:** [docs/index.md](docs/index.md) · [docs/architecture.md](docs/architecture.md)
