# Changelog — agloom

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-12

### Added
- `create_agent()` factory with 9 execution patterns: DIRECT, REACT, SUPERVISOR, PIPELINE, PLANNER_EXECUTOR, REFLECTION, SWARM, BLACKBOARD, HYBRID_DAG.
- Dynamic query classification via LLM-powered analyzer.
- Frozen agent mode for batch workloads (classify once, execute many) with configurable TTL.
- Skill learning system: auto-extraction, generation, lifecycle management, and versioning.
- Feedback system: auto-evaluation, trend detection, user feedback handlers (LTS, webhook, composite).
- Session memory (max_turns) and long-term store integration.
- Human-in-the-loop (HITL) at 4 levels: pattern interrupt, tool interrupt, worker gates, signal queue.
- `robust_structured_call()` with multi-strategy retry and model-agnostic fallback.
- `CircuitBreaker` for fast-fail after consecutive LLM API failures.
- `LLMSemaphore` for global LLM concurrency gating.
- `AsyncRateLimiter` for token-bucket rate limiting.
- `safe_create_task()` for fire-and-forget background tasks with exception logging.
- Async context manager on `UnifiedAgent` for graceful resource cleanup.
- `abatch()` method for parallel multi-query invocation.
- Thread pool offloading for sync Qdrant and disk I/O operations.
- `asyncio.Lock` protection for lazy init (MCP, skills) and cache access.
- Configurable parameters via `create_agent()`: timeouts, retries, rate limits, thresholds.
- Structured logging with JSON/text format support and debug-level control.
- MCP server integration for external tool discovery.
- Query cache with semantic similarity and TTL-based eviction.
- `py.typed` marker for PEP 561 type checking support.
- GitHub Actions CI workflow.
