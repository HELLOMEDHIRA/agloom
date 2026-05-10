# agloom-cli

**agloom CLI** — terminal client for agloom (Ink + React). Connects to `agloom-runtime` over AGP (stdio), with streaming turns and HITL prompts.

## Development

From **`agloom_cli/`** (this directory is the npm package root):

```bash
npm install
npm run build
npm run dev
```

AGP wire types live in **`src/types/agp.ts`** — keep it identical to `agloom_web/src/lib/agp/types.ts`.

- **Repo:** [github.com/HELLOMEDHIRA/agloom](https://github.com/HELLOMEDHIRA/agloom) · package path `agloom_cli/`
