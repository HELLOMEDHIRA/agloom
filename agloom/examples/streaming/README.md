# Streaming

**`streaming.py`** — two streaming modes side-by-side:

| Function            | Method                   | Output                                             |
| ------------------- | ------------------------ | -------------------------------------------------- |
| `demo_token_stream` | `agent.astream()`        | raw token strings                                  |
| `demo_event_stream` | `agent.astream_events()` | typed events (thinking, token, tool_call, done, …) |

```bash
uv run streaming.py
```

`astream_events` is the recommended approach for building UIs on top of `agloom` — it is exactly what the `agloom_cli` and `agloom_web` frontends consume via AGP.
