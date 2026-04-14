# Changelog

## [0.1.2] — 2026-04-14

### Added

- **Task Delegation System** — 4 composable delegation patterns for multi-agent workflows:
    - `as_tool()` — wrap any agent as a LangChain tool for use in another agent's tool loop
    - `register_handoff()` — transparent classifier-driven routing to specialist agents
    - `delegates=[]` parameter on `create_agent()` — hierarchical delegation with `adelegate()` for explicit dispatch
    - `adelegate_background()` / `await_background()` / `cancel_background()` / `background_status()` — fire-and-forget background delegation with full lifecycle management
- New types: `HandoffTarget`, `BackgroundDelegationManager`, `BackgroundTask`, `BackgroundTaskStatus`
- Delegation context injection into classifier prompt — registered delegates are visible to the routing LLM
- SEC 28 test suite: 28 tests covering all 4 delegation patterns (unit + LLM integration)
- Documentation: `docs/features/delegation.md` with full API reference and examples

## [0.1.1] — 2026-04-13

### Added

- Real-time token-by-token streaming for ALL patterns (REACT, SUPERVISOR, DIRECT, etc.) via `astream_events()` — tokens now stream during each LLM call, not after completion
- `StepType.TOKEN` enum value for token events in step traces
- `tool_call_id` correlation: `tool_call` and `tool_result` events/steps now include an `id` field linking each call to its result (essential for parallel tool execution tracking)
- Combined token + event streaming in `astream_events()` — provides both structured step events AND real-time token chunks in a single stream
- Live event emission during execution: events are pushed to consumers as they happen, not replayed after completion
- `worker_start` events emitted when supervisor workers begin execution
- Full method signatures documented for `ainvoke()`, `astream()`, `astream_events()`, and `abatch()` including `thread_id`, `user_id`, `lt_namespace`, and `context` parameters

### Fixed

- Installation docs showed `import src` instead of `import agloom`
- Installation docs showed version `0.1.0` instead of current version

## [0.1.0] — 2026-04-12

### Added

- `create_agent()` factory with 9 execution patterns: DIRECT, REACT, SUPERVISOR, PIPELINE, PLANNER_EXECUTOR, REFLECTION, SWARM, BLACKBOARD, HYBRID_DAG
- Dynamic query classification via LLM-powered analyzer
- Frozen agent mode for batch workloads with configurable TTL
- Skill learning system: auto-extraction, generation, lifecycle management, and versioning
- Feedback system: auto-evaluation, trend detection, user feedback handlers (LTS, webhook, composite)
- Session memory and long-term store integration
- Human-in-the-loop at 4 levels: pattern, tool, worker, signal
- `robust_structured_call()` with multi-strategy retry
- `CircuitBreaker`, `LLMSemaphore`, `AsyncRateLimiter`
- `safe_create_task()` for background tasks with exception logging
- Async context manager for graceful resource cleanup
- `abatch()` for parallel multi-query invocation
- `astream()` for token streaming, `astream_events()` for live events
- Step tracing (`AgentStep`) and token usage tracking
- Configurable timeouts, retries, rate limits, concurrency
- Structured logging with JSON/text format support
- MCP server integration
- Semantic query cache
- Reserved tool name enforcement
- Duplicate agent name detection with warnings
- `py.typed` marker for PEP 561
