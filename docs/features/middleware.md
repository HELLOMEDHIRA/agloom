# Middleware

agloom supports a lightweight middleware system that lets you transform queries before execution and modify results after execution — without touching the agent's core logic.

## How It Works

Middleware objects are duck-typed — they only need `before_agent` and/or `after_agent` methods:

```python
class LoggingMiddleware:
    async def before_agent(self, query: str, context: dict) -> str | None:
        print(f"[LOG] Query: {query}")
        return None  # return None to keep query unchanged

    async def after_agent(self, result, context: dict):
        print(f"[LOG] Pattern: {result.pattern_used.value}, Tokens: {result.token_usage}")
        return None  # return None to keep result unchanged
```

- **`before_agent(query, context)`** — runs before the pipeline. Return a `str` to replace the query, or `None` to keep it unchanged.
- **`after_agent(result, context)`** — runs after the pipeline. Return an `ExecutionResult` to replace the result, or `None` to keep it unchanged.

Both methods can be sync or async — agloom handles either.

## Configuring Middleware

Pass a list of middleware objects to `create_agent`:

```python
agent = create_agent(
    model=llm,
    middleware=[LoggingMiddleware(), GuardrailMiddleware()],
    name="guarded-agent",
)
```

### Execution order

- `before_agent` hooks run **in order** (first middleware → last middleware)
- `after_agent` hooks run **in reverse order** (last middleware → first middleware)

This follows the "onion" pattern common in web frameworks.

## Practical Examples

### Input sanitization

```python
import re

class SanitizeMiddleware:
    async def before_agent(self, query: str, context: dict) -> str:
        cleaned = re.sub(r'<[^>]+>', '', query)  # strip HTML tags
        return cleaned if cleaned != query else None
```

### Cost tracking

```python
class CostMiddleware:
    def __init__(self, cost_per_1k_tokens: float = 0.002):
        self.cost_per_1k = cost_per_1k_tokens
        self.total_cost = 0.0

    async def after_agent(self, result, context: dict):
        total = result.token_usage.get("total_tokens", 0)
        cost = (total / 1000) * self.cost_per_1k
        self.total_cost += cost
        print(f"Run cost: ${cost:.4f} | Total: ${self.total_cost:.4f}")
        return None
```

### PII redaction

```python
class PIIRedactionMiddleware:
    async def before_agent(self, query: str, context: dict) -> str | None:
        import re
        redacted = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN REDACTED]', query)
        redacted = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL REDACTED]', redacted)
        return redacted if redacted != query else None
```

### Guardrails

```python
class GuardrailMiddleware:
    BLOCKED_TOPICS = ["hack", "exploit", "illegal"]

    async def before_agent(self, query: str, context: dict) -> str | None:
        lower = query.lower()
        for topic in self.BLOCKED_TOPICS:
            if topic in lower:
                raise ValueError(f"Query blocked: contains prohibited topic '{topic}'")
        return None
```

## Combining Multiple Middleware

```python
agent = create_agent(
    model=llm,
    middleware=[
        SanitizeMiddleware(),      # 1st: clean input
        PIIRedactionMiddleware(),  # 2nd: redact PII
        GuardrailMiddleware(),     # 3rd: block unsafe queries
        CostMiddleware(),          # runs after_agent to track costs
    ],
    name="production-agent",
)
```

## Context Dict

The `context` parameter passed to middleware comes from the `context=` kwarg on `ainvoke()`:

```python
result = await agent.ainvoke(
    "Hello",
    context={"tenant_id": "acme", "request_id": "req-123"},
)
```

Middleware can read/write this dict to pass data between hooks:

```python
class TimingMiddleware:
    async def before_agent(self, query, context):
        import time
        context["_start_time"] = time.perf_counter()

    async def after_agent(self, result, context):
        import time
        elapsed = time.perf_counter() - context.get("_start_time", 0)
        print(f"Total time: {elapsed:.2f}s")
```
