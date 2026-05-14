# All Parameters

Complete reference for every `create_agent` parameter. All parameters except `model` are optional.

## Core

| Parameter       | Type             | Default        | Description                                                        |                                                                                                                                                    |
| --------------- | ---------------- | -------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model`         | `BaseChatModel \ | str`           | **required**                                                       | LangChain LLM instance or model-id string (e.g. `"openai:gpt-4o"`). Validated at creation — bare names without a provider prefix trigger a warning |
| `tools`         | `list[BaseTool]` | `None` → `[]`  | Tools the agent can call. See [Tool Calling](../features/tools.md) |                                                                                                                                                    |
| `system_prompt` | `str \           | Callable`      | auto-generated                                                     | Static string or dynamic function `(state) -> str`. See [Dynamic System Prompts](../guides/production.md#dynamic-system-prompts)                   |
| `name`          | `str`            | auto-generated | Agent name used in logging, memory namespaces, and diagnostics     |                                                                                                                                                    |
| `debug`         | `bool`           | `False`        | Enable DEBUG-level structured logging. See [Logging](logging.md)   |                                                                                                                                                    |

### Model Validation

`create_agent()` validates the `model` parameter at creation time:

- **`None` or empty string** → raises `ValueError` immediately
- **String without provider prefix** (e.g. `"gpt-4o"` instead of `"openai:gpt-4o"`) → emits a **warning** with the suggested fix. The agent is still created, so custom endpoints still work.
- **Object without `ainvoke`/`invoke` methods** → emits a **warning** that the object doesn't look like a valid LLM

```python
# These raise ValueError when awaited (async code):
await create_agent(model=None)     # ValueError: model is required
await create_agent(model="")       # ValueError: model string is empty

# These emit a warning but still create the agent:
await create_agent(model="gpt-4o")  # WARNING: looks like a bare model name. Did you mean 'openai:gpt-4o'?
await create_agent(model=42)        # WARNING: no 'ainvoke' or 'invoke' method

# Correct usage — no warnings:
await create_agent(model="openai:gpt-4o")
await create_agent(model=ChatGroq(model="llama-3.3-70b-versatile"))
```

## Memory & Storage

| Parameter             | Type             | Default      | Description                                                                                                                                |                                                                    |
| --------------------- | ---------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `store`               | `BaseStore`      | `None`       | LangGraph store. Enables: long-term memory, skills, feedback                                                                               |                                                                    |
| `memory`              | `SessionMemory`  | auto-created | Per-thread session memory. Auto-created with ephemeral `InMemoryStore` if not provided                                                     |                                                                    |
| `query_cache`         | `dict`           | `None`       | Semantic cache dict from `create_cache()`. See [Query Cache](../features/memory.md#query-cache)                                            |                                                                    |
| `enable_memory_tools` | `bool`           | `True`       | Expose `save_memory`/`recall_memory` tools to the agent (requires `store=`)                                                                |                                                                    |
| `session_max_turns`   | `int`            | `20`         | Max turns to keep in session memory. Only applies to auto-created `SessionMemory`                                                          |                                                                    |
| `auto_summarize`      | `bool`           | `True`       | Auto-summarize conversation history when token count exceeds threshold. See [Auto-Summarization](../features/memory.md#auto-summarization) |                                                                    |
| `summarize_threshold` | `int`            | `200_000`    | Token count that triggers auto-summarization (min 10,000)                                                                                  |                                                                    |
| `summarizer_model`    | `BaseChatModel \ | str`         | `None`                                                                                                                                     | Separate LLM for summarization. `None` = use the agent's own model |
| `user_id`             | `str`            | `None`       | Config-level default user ID. Must also be passed at call time to activate user-scoped LT namespace                                        |                                                                    |

## Human-in-the-Loop

| Parameter                  | Type        | Default | Description                                                |
| -------------------------- | ----------- | ------- | ---------------------------------------------------------- |
| `interrupt_before`         | `list[str]` | `None`  | L1: Pause before these patterns (e.g., `["SUPERVISOR"]`)   |
| `interrupt_after`          | `list[str]` | `None`  | L1: Pause after these patterns                             |
| `interrupt_before_tools`   | `list[str]` | `None`  | L2: Pause before these tool calls                          |
| `interrupt_before_workers` | `list[str]` | `None`  | L3: Pause before these workers                             |
| `interrupt_after_workers`  | `list[str]` | `None`  | L3: Pause after these workers                              |
| `user_callback`            | `Callable`  | `None`  | Async function `(context) -> bool` for interrupt decisions |

## Timeouts & Reliability

| Parameter                | Type    | Default | Description                                 |
| ------------------------ | ------- | ------- | ------------------------------------------- |
| `max_concurrent`         | `int`   | `4`     | Max parallel workers (1-32)                 |
| `max_retries`            | `int`   | `2`     | Worker retry count (0-10)                   |
| `retry_delay`            | `float` | `1.0`   | Seconds between retries                     |
| `llm_timeout`            | `float` | `120.0` | LLM call timeout in seconds                 |
| `classifier_timeout`     | `float` | `60.0`  | Classifier timeout in seconds               |
| `structured_max_retries` | `int`   | `2`     | Structured output retry count               |
| `rate_limit`             | `float` | `None`  | Max LLM calls per second. `None` = no limit |

See [Timeouts & Retries](reliability.md) for details.

### ReAct resilience & skills mirror

| Parameter                                 | Type    | Default | Description                                                                                                                                           |        |                                                                                              |
| ----------------------------------------- | ------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------- |
| `react_force_tool_choice_on_user_turn`    | `bool`  | `True`  | After each user message, ReAct requests a structured tool call (`tool_choice=required`) so providers that omit tools still emit a valid tool payload. |        |                                                                                              |
| `react_tool_use_failed_auto_retries_hitl` | `int`   | `2`     | Automatic HITL-backed retries when the model returns malformed tool JSON.                                                                             |        |                                                                                              |
| `react_tool_use_failed_user_rounds`       | `int`   | `3`     | Max user-visible rounds for tool-use recovery before failing the turn.                                                                                |        |                                                                                              |
| `skills_disk_mirror`                      | `Path \ | str \   | None`                                                                                                                                                 | `None` | Optional directory path; when set, mirrors skill artifacts on disk for inspection or backup. |

## Feedback System

| Parameter             | Type    | Default | Description                                       |
| --------------------- | ------- | ------- | ------------------------------------------------- |
| `feedback_handler`    | handler | `None`  | Custom feedback handler (LTS, Webhook, Composite) |
| `low_score_threshold` | `float` | `0.40`  | Score below which skills decay                    |
| `review_every_n_runs` | `int`   | `25`    | Auto-review frequency                             |
| `trend_every_n_runs`  | `int`   | `100`   | Trend analysis frequency                          |

## Reflection

| Parameter                   | Type  | Default | Description                  |
| --------------------------- | ----- | ------- | ---------------------------- |
| `max_reflection_iterations` | `int` | `3`     | Max generate→critique loops  |
| `reflection_threshold`      | `int` | `7`     | Quality score to pass (1-10) |

## Skills

| Parameter    | Type  | Default | Description            |
| ------------ | ----- | ------- | ---------------------- |
| `max_skills` | `int` | `30`    | Max skills in registry |

## Frozen Agent

| Parameter             | Type    | Default    | Description                        |                     |
| --------------------- | ------- | ---------- | ---------------------------------- | ------------------- |
| `frozen`              | `bool`  | `False`    | Classify once, reuse forever       |                     |
| `frozen_template`     | `str`   | `None`     | Template with `{key}` placeholders |                     |
| `input_key`           | `str \  | list[str]` | `"input"`                          | Placeholder name(s) |
| `frozen_analysis_ttl` | `float` | `0`        | Cache TTL in seconds (0 = never)   |                     |

## Delegation

| Parameter   | Type                 | Default         | Description |                                                                                       |
| ----------- | -------------------- | --------------- | ----------- | ------------------------------------------------------------------------------------- |
| `delegates` | `list[UnifiedAgent \ | HandoffTarget]` | `None`      | Child agents for hierarchical delegation. See [Delegation](../features/delegation.md) |

Delegation can also be configured at runtime:

- `agent.register_handoff(target, ...)` — add transparent hand-off targets after creation
- `agent.as_tool()` — wrap agent as a LangChain tool for another agent's tool list

## Advanced

| Parameter                | Type                    | Default     | Description                                                                                                                                                                         |                                                                                                             |                                                                                                                                                                                                              |
| ------------------------ | ----------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `middleware`             | `list`                  | `()`        | Before/after agent middleware. See [Middleware](../features/middleware.md)                                                                                                          |                                                                                                             |                                                                                                                                                                                                              |
| `response_format`        | Pydantic model          | `None`      | Structured output schema (extra LLM reformat pass). See [Structured Output](../guides/production.md#structured-output)                                                              |                                                                                                             |                                                                                                                                                                                                              |
| `state_schema`           | `type`                  | `None`      | Stored on `AgentConfig` for LangGraph compatibility (custom compiled graphs). The default `UnifiedAgent` execution path does not require it.                                        |                                                                                                             |                                                                                                                                                                                                              |
| `context_schema`         | `type`                  | `None`      | Same as `state_schema` — optional LangGraph context typing when you compile graphs that consume it.                                                                                 |                                                                                                             |                                                                                                                                                                                                              |
| `checkpointer`           | `Checkpointer`          | `None`      | LangGraph checkpointer for state persistence. See [Checkpointer](../guides/production.md#checkpointer-state-persistence-and-inspection)                                             |                                                                                                             |                                                                                                                                                                                                              |
| `mcp_servers`            | `list[MCPServerConfig]` | `None`      | MCP server connections. See [MCP Servers](../features/mcp.md)                                                                                                                       |                                                                                                             |                                                                                                                                                                                                              |
| `max_step_output_length` | `int`                   | `0`         | Max chars for step input/output in traces. `0` = no truncation (default — full output preserved). Set to e.g. `500` to limit memory usage                                           |                                                                                                             |                                                                                                                                                                                                              |
| `fallback_pattern`       | `PatternType \| None`       | `None`       | **Internal** classifier hint; not set by CLI/YAML. `None` lets routing follow classifier defaults (e.g. REACT with tools, DIRECT without). |
| `harness`                | `bool`                  | `False`     | Inject progress + git tools (`initialize_project`, `bootstrap_progress`, task CRUD, `git_*`). **Requires `store=`**; ignored without a store. See [Harness](../features/harness.md) |                                                                                                             |                                                                                                                                                                                                              |
| `harness_project_name`   | `str`                   | `"project"` | Scopes the `ProgressTracker` / artifact key together with `name`                                                                                                                    |                                                                                                             |                                                                                                                                                                                                              |
| `cli_tools`              | `bool \                 | dict \      | None`                                                                                                                                                                               | `None`                                                                                                      | Built-in sandboxed CLI tools (`read_file`, `bash`, …). `True` uses defaults; dict overrides `working_dir`, `allow_shell`, `allow_network`, `sandbox`, `task_tool`. See [CLI tools](../features/cli-tools.md) |

## Runtime Parameters (Method Signatures)

These parameters are passed at invocation time to `ainvoke()`, `astream()`, `astream_events()`, and `abatch()`:

| Parameter        | Type     | Default    | Description                                |                                                             |
| ---------------- | -------- | ---------- | ------------------------------------------ | ----------------------------------------------------------- |
| `query`          | `str \   | dict`      | **required**                               | The input query. `dict` only valid for `frozen=True` agents |
| `thread_id`      | `str \   | None`      | `None`                                     | Session ID for memory isolation. `None` = ephemeral         |
| `user_id`        | `str \   | None`      | `None`                                     | Stable cross-session identity for LT namespace              |
| `lt_namespace`   | `tuple \ | None`      | `None`                                     | Explicit shared namespace (multi-agent)                     |
| `context`        | `dict \  | None`      | `None`                                     | Arbitrary context passed to middleware and callbacks        |
| `stream_mode`    | `str`    | `"tokens"` | `astream()` only: `"tokens"` or `"result"` |                                                             |
| `max_concurrent` | `int`    | `5`        | `abatch()` only: concurrent query limit    |                                                             |

### Full method signatures

```python
await agent.ainvoke(query, *, thread_id=None, user_id=None,
                    lt_namespace=None, context=None)

async for token in agent.astream(query, *, thread_id=None, user_id=None,
                                  lt_namespace=None, context=None,
                                  stream_mode="tokens")

async for event in agent.astream_events(query, *, thread_id=None,
                                         user_id=None, lt_namespace=None,
                                         context=None)

await agent.abatch(queries, *, thread_id=None, user_id=None,
                   lt_namespace=None, context=None, max_concurrent=5)
```

## Example: Minimal

```python
async def main():
    agent = await create_agent(model=llm)
```

## Example: Production

```python
async def main():
    agent = await create_agent(
        model=llm,
        tools=[search, calculate],
        system_prompt="You are a data analyst. Be precise and cite sources.",
        name="analyst",
        store=InMemoryStore(),          # enables long-term memory, skills, feedback
        # memory= is auto-created; session_max_turns controls its size
        debug=False,
        max_concurrent=8,
        max_retries=3,
        llm_timeout=60.0,
        rate_limit=10.0,
        feedback_handler=LTSFeedbackHandler(),
        session_max_turns=50,
    )

    # At call time — pass thread_id for session continuity
    result = await agent.ainvoke("Analyze Q3 data", thread_id="session-1", user_id="analyst-42")
```
