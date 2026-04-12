# Changelog

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
