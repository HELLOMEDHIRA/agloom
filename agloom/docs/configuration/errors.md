# Errors & Warnings Reference

A complete reference of every error and warning agloom can produce, what triggers them, and how to resolve them.

## Validation Errors (raised at create_agent time)

These are `ValueError` exceptions raised immediately when `create_agent` is called with invalid parameters. You see them before any LLM call happens.

| Error | Cause | Fix |
| --- | --- | --- |
| `model is required` | `model=None` | Pass a valid LLM instance |
| `name must be non-empty` | `name=""` | Use a non-empty string or omit (auto-generated) |
| `1 ≤ max_concurrent ≤ 32` | `max_concurrent=0` or `>32` | Use a value between 1 and 32 |
| `0 ≤ max_retries ≤ 10` | `max_retries=-1` or `>10` | Use a value between 0 and 10 |
| `unknown pattern in interrupt_before` | `interrupt_before=["INVALID"]` | Use valid pattern names: DIRECT, REACT, SUPERVISOR, etc. |
| `user_callback must be callable` | `user_callback=42` | Pass an async function |
| Frozen agent is not locked yet | Internal error before first call | Run one `ainvoke` / `astream` first to classify, or call `reset_frozen()` |
| `Tool name(s) X are reserved by agloom` | Tool name uses `agloom_` prefix or matches internal names | Rename your tool outside `agloom_*`. Internal tools: `agloom_save_memory`, `agloom_recall_memory`, `agloom_load_skill`, `agloom_recall_tool_artifact` |

## Runtime Warnings (logged, non-fatal)

These are warnings logged during execution. They don't crash your agent — agloom handles them gracefully.

### Tool Warnings

| Warning | Cause | Action |
| --- | --- | --- |
| `normalize_tools: unknown type <class 'X'> — skipped.` | Non-tool object in tools list | Remove it or wrap it with `@tool` |
| `normalize_tools: dict tool has no callable — skipped.` | Dict tool missing `func` key | Add a `func` key with a callable |

### Memory Warnings

| Warning | Cause | Action |
| --- | --- | --- |
| `MemoryInjection: context trimmed to N chars` | Injected memory too long | Increase `max_chars` or reduce `last_n`/`store_limit` |
| `SessionMemory auto-created with ephemeral InMemoryStore` | `memory=` set but no persistent store | Normal if you don't need persistence |

### Pattern Warnings

| Warning | Cause | Action |
| --- | --- | --- |
| `No handler for pattern 'X' — falling back to REACT` | Classifier selected a pattern with no handler | Normal — REACT is a safe fallback |
| `[Classifier] [coerced X→REACT: query requires registered tool calls]` | Classifier picked DIRECT, REFLECTION, or multi-worker pattern without `required_tools` for a tool-requiring query | Normal — runtime enforces REACT or worker tool inheritance |
| `response_format: structured call returned None — using raw output` | Structured output failed | Check your `response_format` Pydantic model |
| `response_format failed (Error) — using raw output` | Structured output raised an exception | Model may not support structured output |

### HITL Warnings

| Warning | Cause | Action |
| --- | --- | --- |
| Interrupt lists set but `user_callback` is missing — gates are transparent | HITL configured without a callback | Pass `user_callback=async_fn` |
| `[HITL-L1] user_callback raised Error — continuing (fail-open)` | Your callback threw an exception | Fix your callback function |

### Skill Warnings

| Warning | Cause | Action |
| --- | --- | --- |
| `seed skill generation failed — non-fatal` | First-time skill bootstrap failed | Normal — skills will be learned from runs |
| `skill_injector failed — proceeding without` | Skill injection error | Skills degraded but agent works |
| `skill_learner failed — non-fatal` | Skill extraction error | Agent works, skill not saved |
| `skill_lifecycle failed — non-fatal` | Lifecycle management error | Non-critical |

### Feedback Warnings

| Warning | Cause | Action |
| --- | --- | --- |
| `feedback() failed — non-fatal` | Feedback submission error | Check store connectivity |
| `build_feedback_system failed — feedback disabled` | Feedback system init error | Check store/handler config |
| `feedback hooks failed — non-fatal` | Post-run feedback hook error | Non-critical |
| `CompositeHandler: X failed for run Y: error` | One handler in composite failed | Other handlers still ran |

### Cache Warnings

| Warning | Cause | Action |
| --- | --- | --- |
| `cache_get failed — proceeding` | Cache read error | Agent works, no cache benefit |
| `cache_set failed — non-fatal` | Cache write error | Result not cached |

### Agent Name Warnings

| Warning | Cause | Action |
| --- | --- | --- |
| `Multiple agents named 'X' share the same LongTermStore` | Same name + same store | Intentional sharing is fine; rename if unintentional |

## Invoke input errors (at `ainvoke` / `astream` time)

| Error | Cause | Fix |
| --- | --- | --- |
| `Invoke input must be {"messages": [...]}` | Dict without a `messages` key | Use LangChain shape: `{"messages": [{"role": "user", "content": "..."}]}` or a plain string |
| `invoke input 'messages' must be a non-empty list` | Empty `messages` | Pass at least one message |
| `must include at least one user/human message` | No user role in `messages` | Add `{"role": "user", "content": "..."}` |

See [Invoke input](../concepts/create-agent.md#invoke-input-langchain-shape) and [Frozen agents — batch](../features/frozen-agents.md#batch-processing).

## Fatal Errors (exceptions during execution)

| Error | Cause | Action |
| --- | --- | --- |
| `MCPConnectionError` | MCP connect failed on first invoke (transport error, `get_tools` failure, or server returned **zero** tools/resources/prompts) | Fix server URL/transport/auth; verify the MCP server exposes tools. See [MCP connect failures](../features/mcp.md#connect-failures). |
| `TimeoutError` / REACT timed out | Per-call or graph wall clock exceeded | Increase `llm_timeout` (per model call) and `react_graph_timeout` (streamed REACT graph). See [Reliability](reliability.md) |
| `unhandled errors in a TaskGroup` | Wrapper around a real failure (MCP tool, provider, network) | Upgrade agloom: REACT/MCP unwrap the root cause in ``error`` / ``output``. Fix the underlying ``PermissionError``, ``ConnectionError``, etc. |
| `GraphRecursionError` / REACT step limit | LangGraph `recursion_limit` reached (`react_recursion_limit`, default 25) | Returns **`success=False`** with a stable error — not the last AI message. Raise `create_agent(react_recursion_limit=…)` or simplify the task. See [Reliability](reliability.md) |
| `No user query found in messages` (strict chat templates) | Jinja/template rejection: bad message shape or forced `tool_choice` off the opening turn | Upgrade agloom (LLM wrapper + middleware flatten user blocks; no `tool_choice` override for strict templates). See [LLM resolution — strict chat templates](../guides/llm-resolution.md#strict-chat-templates-and-tool-calling) |
| `RemoteProtocolError` / server disconnected | HTTP stream dropped (LiteLLM, vLLM, MCP HTTP) — often proxy idle timeout or **oversized request body**, not a literal server shutdown | agloom **auto-compacts and retries** transient transport errors (up to 3× on ainvoke/no-tools; stream compact-then-retry once). Full payloads remain in scratchpad via `agloom_recall_tool_artifact`. Optional override: `context_window_tokens`. **Not agloom settings:** `AGLOOM_ISOLATE_STEP_THREADS`, `VLM_*` env vars — agloom runs steps in asyncio, not threads. Extended thinking is auto-disabled for strict chat templates (vLLM/LiteLLM/Qwen). |
| `Context budget exceeded after compaction` (`failure_class=context`) | REACT history still over input budget after compaction | Lower tool payload sizes, use MCP `limit` when available, or raise `context_window_tokens`. Full payloads remain in scratchpad — use `agloom_recall_tool_artifact`. |
| `RateLimitError` | LLM provider rate limit hit | Set `rate_limit` to throttle calls |
| `CircuitBreakerOpen` | Too many consecutive LLM failures | Wait for cooldown or check provider status |

## Event Errors (from astream_events)

| Event | When emitted | What it means |
| --- | --- | --- |
| `error` | Execution failed during `astream_events()` | Contains `error` field with the message. Emitted on REACT **timeouts** and **step-limit** hits (before `done` with `success=False`). The stream terminates after this event |
