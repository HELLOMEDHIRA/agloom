# Quickstart (5 minutes)

## 1. Install

```bash
pip install agloom
npm install -g agloom-cli
```

Verify Python bridge:

```bash
agloom-runtime providers list | head
```

## 2. Set an API key

Example with Groq (free tier):

```bash
export GROQ_API_KEY=gsk_...
```

Other providers: see [Models & providers](models.md).

## 3. Ask a one-shot question (direct mode)

```bash
agloom -m groq:meta-llama/llama-3.3-70b-versatile "Summarize pyproject.toml in one paragraph"
```

If CLI tools are enabled (default), the agent may ask to **read files** — approve in the terminal when prompted.

## 4. Open the full TUI

```bash
agloom -m groq:meta-llama/llama-3.3-70b-versatile
```

(with no positional prompt). Type `/help` for slash commands.

## 5. Pipe and JSON (scripting)

```bash
agloom -m groq:meta-llama/llama-3.3-70b-versatile -q "list all .py files under agloom" --json | head -5
```

Without `--json`, quiet mode (`-q`) keeps stdout focused on assistant text and trims extra stderr. With `--json`, stdout is **only** NDJSON AGP events (no plain-text assistant stream); use `--json` alone when piping to `jq` or log processors — combining `-q` and `--json` is for silencing stderr, not for switching `--json` back to plain text.

## Next steps

- [Models & providers](models.md) — prefixes and catalogs
- [Config & environment](config.md) — `agloom.yaml`
- [Recipes](recipes.md) — PR review, tests, logs
- [Direct mode](direct-mode.md) — exit codes and automation
