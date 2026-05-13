# Direct mode

Direct mode runs **one prompt** (or stdin), streams or buffers the answer, then exits. It uses the same **`agloom-runtime`** bridge as the TUI without fullscreen Ink.

## When it activates

- A **positional** prompt: `agloom "explain this repo"`
- **`--prompt` / `-p`**
- **Stdin piped** when no TTY (or combined with explicit prompt flags)

If stdin holds piped content, it is merged with explicit prompt flags using the same rules as the interactive CLI (stdin body plus your prompt when both are present).

## Common patterns

```bash
# Positional
agloom "what is README about?"

# Explicit prompt flag
agloom -p "summarize pyproject.toml"

# Pipe context
cat README.md | agloom "summarize this"

# Quiet: assistant text only
agloom -q "list python files in agloom"

# NDJSON event stream for jq / logs
agloom --json "say hello" | head

# No streaming (single assistant message at end)
agloom --no-stream "long task"
```

## HITL in direct mode

Tool approvals still arrive over AGP. Controls:

| Flag             | Behavior                                                                |
| ---------------- | ----------------------------------------------------------------------- |
| *(default)*      | Non-TTY stdin → often **auto-reject** gates (see runtime HITL policy).  |
| `--hitl-tty`     | Prompt approve/deny on a controlling terminal.                          |
| `--auto-approve` | Accept all gates (**dangerous** — can run shell/write tools unchecked). |
| `--auto-reject`  | Decline gated tools.                                                    |

Pair **`--auto-approve`** only in locked-down CI with read-only tools if at all.

## Exit codes

| Code    | Meaning                                                |
| ------- | ------------------------------------------------------ |
| **0**   | Success                                                |
| **1**   | Bridge/runtime error, spawn failure, or non-zero child |
| **2**   | Invalid arguments (Python argparse) when surfaced      |
| **130** | Typical Ctrl+C (`128 + SIGINT`)                        |

Exact mapping follows Node child exit codes from `agloom-runtime`.

## Script recipes

### Extract structured notes from JSON stream

```bash
agloom --json "ping" | jq -r 'select(.type=="message.assistant") | .data.text'
```

### Commit message helper

See [Recipes](recipes.md).

```bash
git diff --staged | agloom -q "write a conventional commit message"
```

## See also

- [Flags](flags.md) — `--quiet`, `--json`, `--no-stream`, `--no-color`
- [Tools & HITL](tools-hitl.md)
- [Runtime CLI](../agloom/runtime/cli.md)
