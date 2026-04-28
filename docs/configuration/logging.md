# Logging & Debug

## Debug Mode

Enable detailed logging with `debug=True`:

```python
async def main():
    agent = await create_agent(model=llm, debug=True, name="my-agent")
```

### debug=True output

```
21:04:29 DEBUG unified_agent — [my-agent] Analysis: {pattern: DIRECT, complexity: 0, ...}
21:04:29 INFO  classifier — [Classifier] Pattern=DIRECT | Complexity=0/10
21:04:29 INFO  unified_agent — [my-agent] DIRECT short-circuit — 1 LLM call total.
21:04:29 DEBUG unified_agent — [my-agent] SessionMemory auto-created with ephemeral InMemoryStore.
```

### debug=False output (default)

```
21:04:29 INFO  classifier — [Classifier] Pattern=DIRECT | Complexity=0/10
21:04:29 INFO  unified_agent — [my-agent] DIRECT short-circuit — 1 LLM call total.
```

DEBUG-level messages are suppressed, leaving only INFO and above.

## Log Format

Set the `LOG_FORMAT` environment variable:

=== "Text (default)"

    ```bash
    export LOG_FORMAT=text
    ```

    Output:
    ```
    21:04:29 INFO  classifier — [Classifier] Pattern=DIRECT | Complexity=0/10
    ```

=== "JSON (for log aggregators)"

    ```bash
    export LOG_FORMAT=json
    ```

    Output:
    ```json
    {"timestamp": "2026-04-12T21:04:29", "level": "INFO", "logger": "classifier", "message": "[Classifier] Pattern=DIRECT | Complexity=0/10"}
    ```

## Package-Level Control

Control the log level for all agloom loggers programmatically:

```python
from agloom import configure_package_logging

configure_package_logging("DEBUG")    # everything
configure_package_logging("INFO")     # normal (default)
configure_package_logging("WARNING")  # suppress info logs
configure_package_logging("ERROR")    # errors only
configure_package_logging("CRITICAL") # silent
```

## What Gets Logged

| Component | INFO logs | DEBUG logs |
|-----------|-----------|------------|
| Classifier | Pattern selected, complexity | Full analysis JSON |
| Unified Agent | Pattern execution, step counts | Memory injection, cache operations |
| Worker | Worker start/end | Worker config, retry attempts |
| Feedback | User feedback applied | Score calculations |
| Skills | Skill injected | Skill matching, lifecycle events |
| Memory | Trim warnings | Context build, injection |

## Suppressing Third-Party Logs

agloom uses `httpx`, `langchain`, and other libraries that may produce their own logs. To suppress them:

```python
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)
```
