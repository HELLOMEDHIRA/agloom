# HITL tool allowlist (persistent)

When human-in-the-loop gates a **tool call**, the UI can respond with a decision that adds the tool name to an **allowlist**. On subsequent turns, ReAct middleware **skips the HITL prompt** for tools in that set (while other safeguards remain).

## Default file location

If **`--hitl-allowlist-path`** is **not** passed to `agloom-runtime serve`, the runtime uses:

**`.agloom/hitl_tool_allowlist.json`** under the current working directory.

The file format is JSON:

```json
{
  "tools": ["execute", "bash"]
}
```

Loads merge into the in-memory set at startup; **`decision=allowlist`** appends and saves atomically.

## Runtime flags

| Flag                                       | Effect                                                         |
| ------------------------------------------ | -------------------------------------------------------------- |
| `--hitl-allowlist-path /path/to/file.json` | Use a specific path (create parent dirs on save as needed).    |
| `--no-hitl-allowlist-persist`              | Never read/write disk; allowlist exists only for this process. |

These apply to both **stdio** and **WebSocket** transports (the runtime passes the path through to the component that bridges HITL over AGP).

## Library / AGP

When embedding **`agloom-runtime`** or building a custom AGP driver, pass the same path and persistence flags the CLI uses — approved tool names are loaded at startup and updated when the user chooses **allowlist** in the HITL UI.

Subsequent invocations of those tools **skip the prompt** (other safeguards unchanged).

## See also

- [Human-in-the-Loop](hitl.md)
- [Runtime CLI](../runtime/cli.md)
