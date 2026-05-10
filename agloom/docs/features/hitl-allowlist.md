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

| Flag | Effect |
|------|--------|
| `--hitl-allowlist-path /path/to/file.json` | Use a specific path (create parent dirs on save as needed). |
| `--no-hitl-allowlist-persist` | Never read/write disk; allowlist exists only for this process. |

These apply to both **stdio** and **WebSocket** transports (session loop wires `HITLBridge` with the path).

## Library / AGP

- **`HITLBridge`** accepts **`tool_allowlist`** and **`allowlist_persist_path`**.
- **`HumanApprovalMiddleware`** respects **`tool_allowlist`** to skip approval when the tool is already allowed.

## See also

- [Human-in-the-Loop](hitl.md)
- [Runtime CLI](../runtime/cli.md)
