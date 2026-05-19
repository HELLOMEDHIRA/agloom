# Errors & Warnings Reference

A complete reference of every error and warning agloom can produce, what triggers them, and how to resolve them.

## Validation Errors (raised at create_agent time)

These are `ValueError` exceptions raised immediately when `create_agent` is called with invalid parameters. You see them before any LLM call happens.

| Error                                            | Cause                                           | Fix                                                                      |
| ------------------------------------------------ | ----------------------------------------------- | ------------------------------------------------------------------------ |
| `model is required`                              | `model=None`                                    | Pass a valid LLM instance                                                |
| `name must be non-empty`                         | `name=""`                                       | Use a non-empty string or omit (auto-generated)                          |
| `1 ≤ max_concurrent ≤ 32`                        | `max_concurrent=0` or `>32`                     | Use a value between 1 and 32                                             |
| `0 ≤ max_retries ≤ 10`                           | `max_retries=-1` or `>10`                       | Use a value between 0 and 10                                             |
| `unknown pattern in interrupt_before`            | `interrupt_before=["INVALID"]`                  | Use valid pattern names: DIRECT, REACT, SUPERVISOR, etc.                 |
| `user_callback must be callable`                 | `user_callback=42`                              | Pass an async function                                                   |
| `frozen=True requires non-empty frozen_template` | `frozen=True` without template                  | Provide `frozen_template="..."`                                          |
| `frozen=True requires non-empty input_key`       | `input_key=[]`                                  | Provide at least one key                                                 |
| `query must be a dict for frozen agents`         | Passing `str` to `ainvoke()` when `frozen=True` | Pass a dict matching `input_key` (e.g., `{"input": "text"}`)             |
| `Tool name(s) X are reserved by agloom`          | Tool name conflicts with internal names         | Rename your tool. Reserved: `save_memory`, `recall_memory`, `load_skill` |

## Runtime Warnings (logged, non-fatal)

These are warnings logged during execution. They don't crash your agent — agloom handles them gracefully.

### Tool Warnings

| Warning                                                 | Cause                         | Action                            |
| ------------------------------------------------------- | ----------------------------- | --------------------------------- |
| `normalize_tools: unknown type <class 'X'> — skipped.`  | Non-tool object in tools list | Remove it or wrap it with `@tool` |
| `normalize_tools: dict tool has no callable — skipped.` | Dict tool missing `func` key  | Add a `func` key with a callable  |

### Memory Warnings

| Warning                                                   | Cause                                 | Action                                                |
| --------------------------------------------------------- | ------------------------------------- | ----------------------------------------------------- |
| `MemoryInjection: context trimmed to N chars`             | Injected memory too long              | Increase `max_chars` or reduce `last_n`/`store_limit` |
| `SessionMemory auto-created with ephemeral InMemoryStore` | `memory=` set but no persistent store | Normal if you don't need persistence                  |

### Pattern Warnings

| Warning                                                             | Cause                                         | Action                                      |
| ------------------------------------------------------------------- | --------------------------------------------- | ------------------------------------------- |
| `No handler for pattern 'X' — falling back to REACT`                | Classifier selected a pattern with no handler | Normal — REACT is a safe fallback           |
| `response_format: structured call returned None — using raw output` | Structured output failed                      | Check your `response_format` Pydantic model |
| `response_format failed (Error) — using raw output`                 | Structured output raised an exception         | Model may not support structured output     |

### HITL Warnings

| Warning                                                                                       | Cause                                  | Action                        |
| --------------------------------------------------------------------------------------------- | -------------------------------------- | ----------------------------- |
| Interrupt lists set but `user_callback` is missing — gates are transparent | HITL configured without a callback | Pass `user_callback=async_fn` |
| `[HITL-L1] user_callback raised Error — continuing (fail-open)`                               | Your callback threw an exception       | Fix your callback function    |

### Skill Warnings

| Warning                                      | Cause                             | Action                                    |
| -------------------------------------------- | --------------------------------- | ----------------------------------------- |
| `seed skill generation failed — non-fatal`   | First-time skill bootstrap failed | Normal — skills will be learned from runs |
| `skill_injector failed — proceeding without` | Skill injection error             | Skills degraded but agent works           |
| `skill_learner failed — non-fatal`           | Skill extraction error            | Agent works, skill not saved              |
| `skill_lifecycle failed — non-fatal`         | Lifecycle management error        | Non-critical                              |

### Feedback Warnings

| Warning                                            | Cause                           | Action                     |
| -------------------------------------------------- | ------------------------------- | -------------------------- |
| `feedback() failed — non-fatal`                    | Feedback submission error       | Check store connectivity   |
| `build_feedback_system failed — feedback disabled` | Feedback system init error      | Check store/handler config |
| `feedback hooks failed — non-fatal`                | Post-run feedback hook error    | Non-critical               |
| `CompositeHandler: X failed for run Y: error`      | One handler in composite failed | Other handlers still ran   |

### Cache Warnings

| Warning                         | Cause             | Action                        |
| ------------------------------- | ----------------- | ----------------------------- |
| `cache_get failed — proceeding` | Cache read error  | Agent works, no cache benefit |
| `cache_set failed — non-fatal`  | Cache write error | Result not cached             |

### Agent Name Warnings

| Warning                                                  | Cause                  | Action                                               |
| -------------------------------------------------------- | ---------------------- | ---------------------------------------------------- |
| `Multiple agents named 'X' share the same LongTermStore` | Same name + same store | Intentional sharing is fine; rename if unintentional |

## Fatal Errors (exceptions during execution)

| Error                | Cause                             | Action                                     |
| -------------------- | --------------------------------- | ------------------------------------------ |
| `TimeoutError`       | LLM call exceeded `llm_timeout`   | Increase timeout or check LLM provider     |
| `RateLimitError`     | LLM provider rate limit hit       | Set `rate_limit` to throttle calls         |
| `CircuitBreakerOpen` | Too many consecutive LLM failures | Wait for cooldown or check provider status |

## Event Errors (from astream_events)

| Event   | When emitted                               | What it means                                                                         |
| ------- | ------------------------------------------ | ------------------------------------------------------------------------------------- |
| `error` | Execution failed during `astream_events()` | Contains `error` field with the error message. The stream terminates after this event |
