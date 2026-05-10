# Tools

**`tools_and_react.py`** — registers custom `@tool` functions and shows how `agloom`
automatically picks the REACT pattern when tools are present.

```bash
uv run tools_and_react.py
```

The step trace in the output shows every `[classify]`, `[tool_call]`, and `[tool_result]` step with its duration.
