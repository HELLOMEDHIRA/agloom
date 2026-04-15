"""
agloom — Weave intelligent agents from 9 execution patterns.

Auto-classification, skill learning, feedback loops, and production-grade
observability on top of LangChain/LangGraph.

Usage:
    from agloom import create_agent

    agent = create_agent(model=llm, tools=[...])
    result = await agent.ainvoke("Research quantum computing")

    # Or with graceful shutdown:
    async with create_agent(model=llm) as agent:
        result = await agent.ainvoke("Hello")
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agloom")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

from .cache import cache_get, cache_set, create_cache
from .delegation import (
    BackgroundDelegationManager,
    BackgroundTask,
    BackgroundTaskStatus,
    HandoffTarget,
)
from .llm_utils import (
    AsyncRateLimiter,
    CircuitBreaker,
    LLMSemaphore,
    robust_structured_call,
    safe_create_task,
)
from .logging_utils import configure_package_logging, get_logger
from .memory.session import SessionMemory
from .memory.store import LongTermStore
from .models import (
    AgentConfig,
    AgentEvent,
    AgentStep,
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    ResolvedWorkerConfig,
    SignalType,
    StepType,
    SubTask,
    WorkerPlan,
    WorkerResult,
)
from .unified_agent import RESERVED_TOOL_NAMES, UnifiedAgent, create_agent

__all__ = [
    "RESERVED_TOOL_NAMES",
    "AgentConfig",
    "AgentEvent",
    "AgentStep",
    "AsyncRateLimiter",
    "BackgroundDelegationManager",
    "BackgroundTask",
    "BackgroundTaskStatus",
    "CircuitBreaker",
    "ExecutionResult",
    "HandoffTarget",
    "LLMSemaphore",
    "LongTermStore",
    "PatternType",
    "QueryAnalysis",
    "ResolvedWorkerConfig",
    "SessionMemory",
    "SignalType",
    "StepType",
    "SubTask",
    "UnifiedAgent",
    "WorkerPlan",
    "WorkerResult",
    "cache_get",
    "cache_set",
    "configure_package_logging",
    "create_agent",
    "create_cache",
    "get_logger",
    "robust_structured_call",
    "safe_create_task",
]
