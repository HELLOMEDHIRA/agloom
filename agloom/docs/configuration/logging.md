# Logging & debug

Understand what your agent is doing in development and staging. Production should rely on structured logs, LangSmith, or the observability API — not verbose console spam.

## Debug mode

```python
async def main():
    agent = await create_agent(model=llm, debug=True, name="my-agent")
```

### With `debug=True`

```text
21:04:29 DEBUG agent — [my-agent] Analysis: {pattern: DIRECT, complexity: 0, ...}
21:04:29 INFO  classifier — [Classifier] Pattern=DIRECT | Complexity=0/10
21:04:29 INFO  agent — [my-agent] DIRECT short-circuit — 1 LLM call total.
21:04:29 DEBUG agent — [my-agent] SessionMemory auto-created with ephemeral InMemoryStore.
```

### Default (`debug=False`)

```text
21:04:29 INFO  classifier — [Classifier] Pattern=DIRECT | Complexity=0/10
21:04:29 INFO  agent — [my-agent] DIRECT short-circuit — 1 LLM call total.
```

DEBUG lines (full classifier JSON, cache keys, injection detail) are suppressed.

---

## Log format

Set **`LOG_FORMAT`** for aggregators:

=== "Text (default)"

    ```bash
    export LOG_FORMAT=text
    ```

    ```text
    21:04:29 INFO  classifier — [Classifier] Pattern=DIRECT | Complexity=0/10
    ```

=== "JSON"

    ```bash
    export LOG_FORMAT=json
    ```

    ```json
    {"event": "[Classifier] Pattern=DIRECT | Complexity=0/10", "level": "info", "ts": "2026-04-12T21:04:29.123456Z", "logger": "agloom.classifier"}
    ```

    Logs are emitted via **structlog** (stdlib integration); field names are stable for aggregators.

---

## Package log level

```python
from agloom import configure_package_logging

configure_package_logging(debug=True)   # DEBUG on all agloom loggers
configure_package_logging(debug=False)  # INFO (default)
```

---

## What gets logged

| Area | INFO (typical) | DEBUG (extra) |
| ---- | -------------- | ------------- |
| Classifier | Pattern + complexity score | Full analysis payload |
| Agent run | Pattern start, step counts | Memory injection, cache hits |
| Workers | Start / end, retries | Worker config |
| Feedback | Score applied | Handler details |
| Skills | Skill injected | Match scores, lifecycle |
| Memory | Trim warnings | Context assembly |

---

## Quiet third-party loggers

```python
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)
```

---

## See also

- [Observability](../features/observability.md) — LangSmith, step traces, tokens
- [Observability metrics](../guides/observability-metrics.md) — `/observe/healthz`, Prometheus
