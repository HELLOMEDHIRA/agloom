# AGP wire reference (CLI clients)

Build a **custom terminal UI**, CI bot, or IDE plugin on top of **`agloom-runtime`** — the same NDJSON contract the npm **`agloom`** CLI uses.

End-user docs start at [Overview](index.md). Canonical event shapes: [AGP specification](../agloom/protocol/agp.md).

---

## Process model

```text
your client (Node, Python, Go, …)
    │ spawn
    ▼
agloom-runtime serve --transport=stdio
    │ stdout: one JSON object per line (AGP)
    │ stderr: human diagnostics only
    ▼
your parser → dispatch on event.type
```

The CLI does **not** embed Python. It forwards flags to **`agloom-runtime`** and parses stdout.

---

## stdout vs stderr

| Stream | Contents | Parser rule |
| ------ | -------- | ----------- |
| **stdout** | AGP envelopes only | Read line-by-line; `JSON.parse` each non-empty line |
| **stderr** | Startup banners, Python logs, resolver hints | Display to humans; **never** treat as AGP |

Corrupting stdout (color filters, `grep` without line mode, merging stderr into stdout) breaks the bridge.

---

## Envelope shape

Every line is one object:

```jsonc
{
  "v": 1,
  "id": "evt_…",
  "ts": "2026-05-19T12:00:00.000Z",
  "session": "s_…",
  "thread": "t_…",
  "seq": 42,
  "type": "token.delta",
  "data": { }
}
```

Dispatch on **`type`**. Ignore unknown types for forward compatibility.

---

## Minimal client loop (Node)

```javascript
import { spawn } from "node:child_process";
import readline from "node:readline";

const child = spawn("agloom-runtime", [
  "serve", "--transport=stdio",
  "--with-cli-tools", "--cli-tools-working-dir", process.cwd(),
], { stdio: ["pipe", "pipe", "inherit"] });

const rl = readline.createInterface({ input: child.stdout });
rl.on("line", (line) => {
  if (!line.trim()) return;
  const evt = JSON.parse(line);
  handleAgp(evt);
});

function handleAgp(evt) {
  switch (evt.type) {
    case "token.delta":
      process.stdout.write(evt.data.content ?? "");
      break;
    case "message.assistant":
      // Authoritative final text — prefer over streamed deltas
      console.log("\n---\n", evt.data.content);
      break;
    case "tool.call.start":
      console.error("[tool]", evt.data.tool, evt.data.args);
      break;
    case "tool.call.result":
      console.error("[result]", evt.data.tool, evt.data.output_preview?.length);
      break;
    case "hitl.request":
      // Send command.hitl.respond on stdin (see AGP spec)
      break;
    case "metric.tokens":
      console.error("[tokens]", evt.data);
      break;
    default:
      break;
  }
}

// Send a turn (shape depends on your command adapter — CLI uses command.invoke)
```

For inbound commands (`command.invoke`, `command.cancel`, `command.hitl.respond`), write **one JSON object per line** to the runtime’s **stdin**. See [AGP specification — commands](../agloom/protocol/agp.md).

---

## Events every UI should handle

| Tier | Types | Why |
| ---- | ----- | --- |
| **Streaming** | `token.delta`, `message.assistant`, `stream.end` | Chat surface |
| **Tools** | `tool.call.start`, `tool.call.result`, `tool.call.error` | Tool cards; bodies are **full** in `output_preview` when the runtime emits them |
| **Routing** | `progress.step`, `thinking.step`, `pattern.classified` | Infra setup (`progress.step`); routing rationale (`thinking.step` after classify) |
| **Skills** | `skill.applied` | Matched skill ids in `skills` (legacy `skill_names` accepted on parse) |
| **Reasoning** | `token.delta` with `role: "reasoning"` | Model-native reasoning stream (provider-dependent) — separate from `assistant` deltas |
| **HITL** | `hitl.request`, `hitl.granted`, `hitl.denied` | Approvals |
| **Metrics** | `metric.tokens`, `metric.cost` | Sidebar; use rollup fields — do not sum every `token.delta` blindly |
| **MCP** | `runtime.mcp.servers` | Connected servers + `tool_catalog` (name + description per tool) |
| **Lifecycle** | `session.opened`, `session.closed`, `agent.busy`, `agent.idle` | Connection state |

Full catalog: [AGP specification](../agloom/protocol/agp.md). Conceptual guide (trace vs reasoning): [Thinking trace & reasoning streams](../agloom/features/thinking-events.md).

---

## Assistant text: wire vs stream

1. **Stream** `token.delta` for live typing.
2. On **`message.assistant`**, treat **`data.content`** as the **authoritative** final message (may differ slightly from deltas after sanitization).
3. Strip internal envelopes like `[agloom:tool_result]…` from display text if they appear in legacy paths.
4. If the model emits **JSON-shaped tool calls in plain text** (no native `tool_calls`), hide that blob from the user — the runtime recovers on the Python side; clients should not surface raw tool JSON as the answer.

The npm CLI implements this in **`finalizeAssistantMessage`** / **`strayToolJson`** (see repo `agloom_cli/src/utils/`).

---

## Tool results on the wire

`tool.call.result` includes:

| Field | Meaning |
| ----- | ------- |
| `output_preview` | Full tool return body (not capped at 1024 in current runtime) |
| `output_bytes` | Byte length of the preview string |
| `truncated` | `false` when the full body is inline; `true` only if a future cap applies |

UIs should render **`output_preview` in full** (wrap / scroll), not collapse behind toggles, unless you impose your own limits for memory.

---

## Token metrics

- **`metric.tokens`** — per-invocation rollup suitable for status bars (`input_tokens`, `output_tokens`, optional `total_tokens`).
- **`token.delta`** — streaming chunks; **do not** add every delta to a session total (double-counts).

Display pattern used by CLI/web: `↑12k ↓3k` when both directions are present.

---

## HITL responses

On `hitl.request`, send **`command.hitl.respond`** with `request_id`, `decision` (`accept` | `deny` | `allowlist`), and optional `reason`. Direct mode flags: [Direct mode](direct-mode.md).

---

## Debugging corrupt streams

| Symptom | Likely cause |
| ------- | ------------- |
| `JSON.parse` failures | Non-AGP bytes on stdout; stderr merged into stdout |
| Missing events | Line buffering; use line-delimited reads, not chunk reads |
| Hung after prompt | Waiting on HITL; use `--hitl-tty` or `--auto-reject` in scripts |
| Raw tool JSON as answer | Client not preferring `message.assistant`; see above |

---

## Related docs

- [AGP specification](../agloom/protocol/agp.md)
- [Runtime CLI](../agloom/runtime/cli.md) — `serve` flags
- [Flags](flags.md) · [Direct mode](direct-mode.md)
- [Runtime architecture](../agloom/runtime/architecture.md)

**Maintainers:** npm bridge layout and tests — repository root **`CONTRIBUTING.md`**.
