# Quickstart (5 minutes)

A minimal path from install to a working terminal session, then one scripted command.

---

## 1. Install

```bash
pip install agloom
npm install -g agloom-cli
agloom-runtime providers list | head   # verify Python bridge
```

---

## 2. Set an API key

```bash
export GROQ_API_KEY=gsk_...
```

Other providers: [Models & providers](models.md).

---

## 3. One-shot question (direct mode)

```bash
agloom -m groq:meta-llama/llama-3.3-70b-versatile \
  "Summarize pyproject.toml in one paragraph"
```

**What happens**

1. CLI starts `agloom-runtime` with your model and working directory
2. Runtime classifies the task and runs the agent (often **REACT** if it reads files)
3. You may see **HITL prompts** before `read_file` — approve or deny in the terminal
4. Assistant text prints to stdout (unless you use `--json`)

---

## 4. Full interactive UI

```bash
agloom -m groq:meta-llama/llama-3.3-70b-versatile
```

- **Main column** — your messages, live assistant stream, **full tool output**, and **reasoning** steps
- **Right sidebar** (`/stats`) — tokens, wire notes, MCP status
- **Composer** — type messages; `/help` for slash commands

Reasoning and tool results are **always visible** — no toggle required.

---

## 5. Pipe and JSON (automation)

```bash
git diff --staged | agloom -q \
  -m groq:meta-llama/llama-3.3-70b-versatile \
  "write a conventional commit message"
```

| Flag | Effect |
| ---- | ------ |
| `-q` | Quieter stderr; stdout focused on the answer |
| `--json` | stdout is **only** AGP NDJSON (for `jq`, log pipelines) |

See [Direct mode](direct-mode.md) for exit codes.

---

## What to try next

| Goal | Page |
| ---- | ---- |
| Script CI or bots | [Direct mode](direct-mode.md) · [Recipes](recipes.md) |
| Tune model and keys | [Models](models.md) · [Config](config.md) |
| Safer file/shell tools | [Tools & HITL](tools-hitl.md) |
| Long multi-session coding | [MCP, memory & harness](mcp-memory-harness.md) |

**Library-only (no terminal UI):** [Python quick start](../agloom/getting-started/quickstart.md)
