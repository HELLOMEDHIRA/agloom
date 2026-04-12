# All Parameters

Complete reference for every `create_agent` parameter. All parameters except `model` are optional.

## Core

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `BaseChatModel` | **required** | Any LangChain-compatible LLM |
| `tools` | `list[BaseTool]` | `None` → `[]` | Tools the agent can call. See [Tool Calling](../features/tools.md) |
| `system_prompt` | `str \| Callable` | auto-generated | Static string or dynamic function `(state) -> str`. Dynamic prompts are called on every invocation |
| `name` | `str` | auto-generated | Agent name used in logging, memory namespaces, and diagnostics |
| `debug` | `bool` | `False` | Enable DEBUG-level structured logging. See [Logging](logging.md) |

## Memory & Storage

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `store` | `BaseStore` | `None` | LangGraph store. Enables: long-term memory, skills, feedback |
| `memory` | `SessionMemory` | `None` | Per-thread session memory |
| `query_cache` | Qdrant client | `None` | Semantic cache for repeat queries |
| `enable_memory_tools` | `bool` | `True` | Expose `save_memory`/`recall_memory` tools to the agent |
| `session_max_turns` | `int` | `20` | Max turns to keep in session memory |
| `user_id` | `str` | `None` | Default user ID for memory namespacing |

## Human-in-the-Loop

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interrupt_before` | `list[str]` | `None` | L1: Pause before these patterns (e.g., `["SUPERVISOR"]`) |
| `interrupt_after` | `list[str]` | `None` | L1: Pause after these patterns |
| `interrupt_before_tools` | `list[str]` | `None` | L2: Pause before these tool calls |
| `interrupt_before_workers` | `list[str]` | `None` | L3: Pause before these workers |
| `interrupt_after_workers` | `list[str]` | `None` | L3: Pause after these workers |
| `user_callback` | `Callable` | `None` | Async function `(context) -> bool` for interrupt decisions |

## Timeouts & Reliability

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_concurrent` | `int` | `4` | Max parallel workers (1-32) |
| `max_retries` | `int` | `2` | Worker retry count (0-10) |
| `retry_delay` | `float` | `1.0` | Seconds between retries |
| `llm_timeout` | `float` | `120.0` | LLM call timeout in seconds |
| `classifier_timeout` | `float` | `30.0` | Classifier timeout in seconds |
| `structured_max_retries` | `int` | `2` | Structured output retry count |
| `rate_limit` | `float` | `None` | Max LLM calls per second. `None` = no limit |

See [Timeouts & Retries](reliability.md) for details.

## Feedback System

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `feedback_handler` | handler | `None` | Custom feedback handler (LTS, Webhook, Composite) |
| `low_score_threshold` | `float` | `0.40` | Score below which skills decay |
| `review_every_n_runs` | `int` | `25` | Auto-review frequency |
| `trend_every_n_runs` | `int` | `100` | Trend analysis frequency |

## Reflection

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_reflection_iterations` | `int` | `3` | Max generate→critique loops |
| `reflection_threshold` | `int` | `7` | Quality score to pass (1-10) |

## Skills

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_skills` | `int` | `30` | Max skills in registry |

## Frozen Agent

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `frozen` | `bool` | `False` | Classify once, reuse forever |
| `frozen_template` | `str` | `None` | Template with `{key}` placeholders |
| `input_key` | `str \| list[str]` | `"input"` | Placeholder name(s) |
| `frozen_analysis_ttl` | `float` | `0` | Cache TTL in seconds (0 = never) |

## Advanced

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `middleware` | `list` | `()` | Before/after agent middleware |
| `response_format` | Pydantic model | `None` | Structured output schema |
| `state_schema` | `type` | `None` | Custom state schema for the graph |
| `context_schema` | `type` | `None` | Custom context schema |
| `checkpointer` | `Checkpointer` | `None` | LangGraph checkpointer for state recovery |
| `mcp_servers` | `list[MCPServerConfig]` | `None` | MCP server connections |

## Example: Minimal

```python
agent = create_agent(model=llm)
```

## Example: Production

```python
agent = create_agent(
    model=llm,
    tools=[search, calculate],
    system_prompt="You are a data analyst. Be precise and cite sources.",
    name="analyst",
    store=InMemoryStore(),
    memory=SessionMemory(),
    debug=False,
    max_concurrent=8,
    max_retries=3,
    llm_timeout=60.0,
    rate_limit=10.0,
    feedback_handler=LTSFeedbackHandler(),
    session_max_turns=50,
)
```
