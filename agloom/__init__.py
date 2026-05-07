"""Multi-pattern agents on LangChain/LangGraph: classification, tools, memory, skills, feedback.

Typical use::

    from agloom import create_agent

    agent = await create_agent(model=llm, tools=[...])
    result = await agent.ainvoke("Hello")

Sync constructor: ``create_agent_sync``. Use ``async with agent:`` (or ``await agent.aclose()``)
to release MCP clients and feedback handlers.
"""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

from .delegation import (
    BackgroundDelegationManager,
    BackgroundTask,
    BackgroundTaskStatus,
    HandoffTarget,
)
from .hitl_contract import HITLEvent, call_user_callback, normalize_react_tool_use_failed_decision
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
from .unified_agent import RESERVED_TOOL_NAMES, UnifiedAgent, create_agent, create_agent_sync

try:
    from .harness import (
        BootstrapState,
        ProgressArtifact,
        ProgressTracker,
        Task,
        TaskPriority,
        TaskStatus,
        TaskStep,
    )
    from .harness.git import GitSession

    _HARNESS_AVAILABLE = True
except ImportError:
    ProgressTracker = None
    GitSession = None
    ProgressArtifact = None
    Task = None
    TaskPriority = None
    TaskStatus = None
    TaskStep = None
    BootstrapState = None
    _HARNESS_AVAILABLE = False

try:
    __version__ = _version("agloom")
except _PackageNotFoundError:
    __version__ = "0.0.0-dev"
del _PackageNotFoundError, _version

__all__ = [
    "RESERVED_TOOL_NAMES",
    "AgentConfig",
    "AgentEvent",
    "AgentStep",
    "AsyncRateLimiter",
    "BackgroundDelegationManager",
    "BackgroundTask",
    "BackgroundTaskStatus",
    "BootstrapState",
    "CircuitBreaker",
    "ExecutionResult",
    "GitSession",
    "HITLEvent",
    "HandoffTarget",
    "LLMSemaphore",
    "LongTermStore",
    "PatternType",
    "ProgressArtifact",
    "ProgressTracker",
    "QueryAnalysis",
    "ResolvedWorkerConfig",
    "SessionMemory",
    "SignalType",
    "StepType",
    "SubTask",
    "Task",
    "TaskPriority",
    "TaskStatus",
    "TaskStep",
    "UnifiedAgent",
    "WorkerPlan",
    "WorkerResult",
    "cache_get",
    "cache_set",
    "call_user_callback",
    "configure_package_logging",
    "create_agent",
    "create_agent_sync",
    "create_cache",
    "get_logger",
    "normalize_react_tool_use_failed_decision",
    "robust_structured_call",
    "safe_create_task",
]


def __getattr__(name: str):
    """Lazy-export cache helpers so ``import agloom`` does not load Qdrant."""
    if name in ("cache_get", "cache_set", "create_cache"):
        from . import cache as _cache

        return getattr(_cache, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | {n for n in globals() if not n.startswith("_")})
