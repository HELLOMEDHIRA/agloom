# agloom-cli

Terminal client for **[agloom](https://github.com/HELLOMEDHIRA/agloom)** — **Ink** + **React** UI over the **AGP** protocol (NDJSON on stdio), driven by **`agloom-runtime`** from the PyPI `agloom` package.

## Install

```bash
pip install agloom
npm install -g agloom-cli
```

Requires **Node.js >= 24.15** and **Python 3.12+** with `agloom` installed so `agloom-runtime` is on `PATH`.

## First run

```bash
export GROQ_API_KEY=...   # or another provider
agloom -m groq:meta-llama/llama-3.3-70b-versatile
```

Set **`AGLOOM_RUNTIME`** only if the Python bridge lives outside your PATH.

## Documentation

**Full CLI docs:** [ReadTheDocs — agloom CLI](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/) (MkDocs nav **agloom CLI**).

Repo copies: [`agloom_cli/docs/`](docs/index.md) — models, flags, config, recipes, troubleshooting.

## Development

```bash
cd agloom_cli
npm install
npm run build
npm test
```
