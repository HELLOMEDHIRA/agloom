# All Parameters

Complete reference for **`create_agent`**. Only **`model`** is required; everything else tunes memory, safety, orchestration, and production guardrails.

!!! info "Call-time options"
    **`thread_id`**, **`user_id`**, and **`context`** are passed to **`ainvoke`** / streaming methods — not to `create_agent`. See [Runtime parameters](#runtime-parameters-method-signatures) below.

## Core

| Parameter       | Type                     | Default        | Description                                                                                                                                       |
| --------------- | ------------------------ | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model`         | `BaseChatModel` or `str` | **required**   | LangChain LLM instance or model-id string (e.g. `"openai:gpt-4o"`). Strings are resolved via `agloom.llm.get_model`. There is no `temperature=` on `create_agent` — set sampling on the model instance (e.g. `ChatOpenAI(temperature=0.2)`) or via runtime YAML when using `agloom-runtime`. Bare names without a provider prefix trigger a warning |
| `tools`         | `list[BaseTool]`         | `None` → `[]`  | Tools the agent can call. See [Tool Calling](../features/tools.md)                                                                                |
| `system_prompt` | `str` or `Callable`      | auto-generated | Static string or dynamic function `(state) -> str`. See [Dynamic System Prompts](../guides/production.md#dynamic-system-prompts)                   |
| `name`          | `str`                    | auto-generated | Agent name used in logging, memory namespaces, and diagnostics                                                                                    |
| `debug`         | `bool`                   | `False`        | Enable DEBUG-level structured logging. See [Logging](logging.md)                                                                                  |

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

| Parameter              | Type                     | Default      | Description                                                                                                                                 |
| ---------------------- | ------------------------ | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `store`                | `BaseStore`              | `None`       | LangGraph store. Enables: long-term memory, skills, feedback                                                                                |
| `memory`               | `SessionMemory`          | auto-created | Per-thread session memory. Auto-created with ephemeral `InMemoryStore` if not provided                                                      |
| `query_cache`          | `dict`, `False`, or `None` | `None` → in-memory default | `None`: enable `default_query_cache()`. `False`: disable caching. Or pass a dict from `create_cache()`. See [Query Cache](../features/memory.md#query-cache) |
| `enable_memory_tools`  | `bool`                   | `True`       | Expose `save_memory`/`recall_memory` tools to the agent (requires `store=`)                                                               |
| `session_max_turns`    | `int`                    | `50`         | Max turns to keep in session memory. Only applies to auto-created `SessionMemory`                                                           |
| `auto_summarize`       | `bool`                   | `True`       | Auto-summarize conversation history when token count exceeds threshold. See [Auto-Summarization](../features/memory.md#auto-summarization) |
| `summarize_threshold`  | `int`                    | `200_000`    | Token count that triggers auto-summarization (min 10,000) when `summarize_max_tokens_budget` is unset                                                                                    |
| `summarize_max_tokens_budget` | `int` or `None`   | `None`       | When set (or inferred from the chat model's `max_tokens`), rolling memory summarizes when stored tokens exceed ~80% of this budget; otherwise `summarize_threshold` applies |
| `summarizer_model`     | `BaseChatModel` or `str` | `None`       | Separate LLM for summarization. `None` = use the agent's own model                                                                        |
| `user_id`              | `str`                    | `None`       | Config-level default user ID. Must also be passed at call time to activate user-scoped LT namespace                                         |

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

| Parameter                                 | Type               | Default | Description                                                                                                                                            |
| ----------------------------------------- | ------------------ | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `react_force_tool_choice_on_user_turn`    | `bool`             | `True`  | After each user message, ReAct requests a structured tool call (`tool_choice=required`) so providers that omit tools still emit a valid tool payload. |
| `react_tool_use_failed_auto_retries_hitl` | `int`              | `2`     | Automatic HITL-backed retries when the model returns malformed tool JSON.                                                                              |
| `react_tool_use_failed_user_rounds`       | `int`              | `3`     | Max user-visible rounds for tool-use recovery before failing the turn.                                                                                 |
| `skills_disk_mirror`                      | `Path` or `str` or `None` | `None` | Optional directory path; when set, mirrors skill artifacts on disk for inspection or backup.                                                          |

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

| Parameter             | Type                   | Default   | Description                                        |
| --------------------- | ---------------------- | --------- | -------------------------------------------------- |
| `frozen`              | `bool`                 | `False`   | Classify once, reuse forever                       |
| `frozen_template`     | `str`                  | `None`    | Template with `{key}` placeholders                 |
| `input_key`           | `str` or `list[str]`   | `"input"` | Placeholder name(s)                                |
| `frozen_analysis_ttl` | `float`                | `0`       | Cache TTL in seconds (0 = never)                   |

## Delegation

| Parameter   | Type                                  | Default | Description                                                                           |
| ----------- | ------------------------------------- | ------- | ------------------------------------------------------------------------------------- |
| `delegates` | list of agents or `HandoffTarget` | `None`  | Child agents for hierarchical delegation. See [Delegation](../features/delegation.md) |

Delegation can also be configured at runtime:

- `agent.register_handoff(target, ...)` — add transparent hand-off targets after creation
- `agent.as_tool()` — wrap agent as a LangChain tool for another agent's tool list

## Advanced

| Parameter                 | Type                      | Default     | Description                                                                                                                                                                                                            |
| ------------------------- | ------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `middleware`              | `list`                    | `()`        | Before/after agent middleware. See [Middleware](../features/middleware.md)                                                                                                                                            |
| `response_format`         | Pydantic model            | `None`      | Structured output schema (extra LLM reformat pass). See [Structured Output](../guides/production.md#structured-output)                                                                                                |
| `state_schema`            | `type`                    | `None`      | Optional LangGraph state typing when you compile custom graphs. Not required for default `ainvoke` usage.                                                                                                               |
| `context_schema`          | `type`                    | `None`      | Same as `state_schema` — optional LangGraph context typing when you compile graphs that consume it.                                                                                                                    |
| `checkpointer`            | `Checkpointer`            | `None`      | LangGraph checkpointer for `get_state` / `get_history` / `resume`. Checkpoints store query, output, steps, and **`analysis`** when classified. See [Checkpointer](../guides/production.md#checkpointer-state-persistence-and-inspection) |
| `mcp_servers`             | `list[MCPServerConfig]`   | `None`      | MCP server connections. See [MCP Servers](../features/mcp.md)                                                                                                                                                          |
| `max_step_output_length`  | `int`                     | `0`         | Max chars for step input/output in traces. `0` = no truncation (default — full output preserved). Set to e.g. `500` to limit memory usage                                                                               |
| `fallback_pattern`        | `PatternType` or `None`   | `None`      | Advanced override for pattern routing. Leave `None` so the classifier chooses (typical: REACT with tools, DIRECT without). Not exposed in CLI/YAML.                                                                            |
| `harness`                 | `bool`                    | `False`     | Inject progress + git tools (`initialize_project`, `bootstrap_progress`, task CRUD, `git_*`). **Requires `store=`**; ignored without a store. See [Harness](../features/harness.md)                                      |
| `harness_project_name`    | `str`                     | `"project"` | Scopes the `ProgressTracker` / artifact key together with `name`                                                                                                                                                       |
| `cli_tools`               | `bool`, `dict`, or `None` | `None`      | Built-in sandboxed CLI tools (`read_file`, `bash`, …). `True` uses defaults; dict overrides `working_dir`, `allow_shell`, `allow_network`, `sandbox`, `task_tool`. See [CLI tools](../features/cli-tools.md)           |
| `require_tool_approval_for_cli_tools` | `bool` | `True` | When `True` and `user_callback` is set, built-in CLI file/shell tools pause for HITL approval before running |

## Recursive orchestration

Optional self-healing execution: spawn follow-up patterns inside one turn with depth/token/LLM-call limits. **Off by default** (`max_pattern_depth=0`). See [Recursive orchestration](../features/orchestration.md).

| Parameter | Type | Default | Description |
| --------- | ---- | ------- | ----------- |
| `max_pattern_depth` | `int` | `0` | **Ceiling** for recursive pattern depth. `0` = legacy single-pass (no orchestration). When `orchestration_plan_from_classifier=True`, the classifier picks per-turn depth ≤ this value. |
| `max_orchestration_tokens` | `int` | `0` | Ceiling for total orchestration tokens across spawns (`0` = unlimited). |
| `max_orchestration_llm_calls` | `int` | `100` | Ceiling for orchestration LLM calls (`0` = unlimited). |
| `enable_auto_escalation` | `bool` | `False` | Master switch: when `True`, post-step evaluation may spawn follow-up patterns (subject to per-turn plan). |
| `orchestration_plan_from_classifier` | `bool` | `True` | When `True` and `max_pattern_depth > 0`, the classifier sets per-turn depth/budgets (clamped to ceilings). When `False`, agent ceilings apply directly every turn. |
| `escalation_rules` | `list[str]` | `["default"]` | Escalation rule set: `default`, `conservative`, or `aggressive`. |
| `enable_pattern_spawns` | `bool` | `True` | Pattern handlers may spawn sub-patterns when orchestration is on. |
| `enable_orchestration_llm_eval` | `bool` | `True` | LLM quality evaluation on each dispatch step; `False` = minimal structural fallback only. |
| `enable_dynamic_dag_nodes` | `bool` | `True` | HYBRID_DAG: reclassify/dispatch only for tool nodes or `complexity >= 7`. |
| `enable_supervisor_worker_dispatch` | `bool` | `True` | SUPERVISOR: per-worker sub-patterns when orchestration is on (no worker HITL on that path). |
| `orchestration_evaluation_llm` | `BaseChatModel` or `str` or `None` | `None` | Optional separate LLM for orchestration evaluation; defaults to main model. |

### Classifier fields (on `result.analysis`)

When orchestration is enabled, the classifier may also return (optional, clamped at runtime):

| Field | Description |
| ----- | ----------- |
| `orchestration_depth` | Suggested max depth for this turn |
| `orchestration_token_budget` | Suggested token budget |
| `orchestration_llm_call_budget` | Suggested LLM call budget |
| `orchestration_auto_escalation` | Suggested auto-escalation for this turn |

## Runtime Parameters (Method Signatures)

These parameters are passed at invocation time to `ainvoke()`, `astream()`, `astream_events()`, and `abatch()`:

| Parameter        | Type              | Default    | Description                                                    |
| ---------------- | ----------------- | ---------- | -------------------------------------------------------------- |
| `query`          | `str` or `dict`   | **required** | The input query. `dict` only valid for `frozen=True` agents |
| `thread_id`      | `str` or `None`   | `None`     | Session ID for memory isolation. `None` = ephemeral           |
| `user_id`        | `str` or `None`   | `None`     | Stable cross-session identity for LT namespace                 |
| `lt_namespace`   | `tuple` or `None` | `None`     | Explicit shared namespace (multi-agent)                       |
| `context`        | `dict` or `None`  | `None`     | Arbitrary context passed to middleware and callbacks          |
| `stream_mode`    | `str`             | `"tokens"` | `astream()` only: `"tokens"` or `"result"`                   |
| `max_concurrent` | `int`             | `5`        | `abatch()` only: concurrent query limit                      |

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

### `resume()` (graph interrupts) {#graph-resume}

Separate from AGP **`command.session.resume`** (client reconnect + event replay). Use **`await agent.resume(value, thread_id=…)`** only after a graph interrupt when a **`checkpointer`** is configured. See [Production — Resuming interrupted runs](../guides/production.md#resuming-interrupted-runs).

## Example: Minimal

```python
async def main():
    agent = await create_agent(model=llm)
```

## Example: Production

```python
from agloom.feedback import LTSFeedbackHandler
from langgraph.store.memory import InMemoryStore

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
