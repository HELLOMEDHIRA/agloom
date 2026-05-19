"""Multi-pattern agentic AI framework built on LangChain/LangGraph.

Batteries-included: classification, tools, memory, skills, HITL, feedback, MCP, multi-agent.

Quickstart — streaming (recommended)::

    from agloom import create_agent

    agent = await create_agent(model="openai:gpt-4o", tools=[...])
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": "Hello"}]},
    ):
        if event.type == "token":
            print(event.data["content"], end="", flush=True)
        elif event.type == "done":
            result = event.data["result"]

AGP-native streaming (agloom CLI, web workspace, observability dashboards)::

    async for envelope in agent.astream_agp_events(
        {"messages": [{"role": "user", "content": "Hello"}]},
    ):
        if envelope.type == "token.delta":
            print(envelope.data.text, end="", flush=True)

Single-turn result (LangChain invoke shape; plain str is also accepted)::

    result = await agent.ainvoke({"messages": [{"role": "user", "content": "Hello"}]})
    print(result.output)

Sync entry point::

    agent = create_agent_sync(model="openai:gpt-4o", tools=[...])
    result = agent.invoke({"messages": [{"role": "user", "content": "Hello"}]})

Use ``async with agent:`` or ``await agent.aclose()`` to release MCP clients and feedback handlers.
"""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

from .delegation import (
    BackgroundDelegationManager,
    BackgroundTask,
    BackgroundTaskStatus,
    HandoffTarget,
)
from .hitl_contract import HITLEvent
from .logging_utils import configure_package_logging
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
from .unified_agent import UnifiedAgent, create_agent, create_agent_sync

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
    "create_agent",
    "create_agent_sync",
    "UnifiedAgent",
    "AgentConfig",
    "AgentEvent",
    "AgentStep",
    "ExecutionResult",
    "PatternType",
    "QueryAnalysis",
    "ResolvedWorkerConfig",
    "SignalType",
    "StepType",
    "SubTask",
    "WorkerPlan",
    "WorkerResult",
    "SessionMemory",
    "LongTermStore",
    "CLI_TOOL_NAMES",
    "HITLEvent",
    "SafetyContext",
    "get_cli_tools",
    "BackgroundDelegationManager",
    "BackgroundTask",
    "BackgroundTaskStatus",
    "HandoffTarget",
    "create_cache",
    "cache_get",
    "cache_set",
    "configure_package_logging",
]

# Harness extra: these names join ``__all__`` when optional deps are installed.
if _HARNESS_AVAILABLE:
    __all__ += [
        "BootstrapState",
        "GitSession",
        "ProgressArtifact",
        "ProgressTracker",
        "Task",
        "TaskPriority",
        "TaskStatus",
        "TaskStep",
    ]


def __getattr__(name: str):
    """Lazy-export heavy submodules: cache (Qdrant), CLI tool registry."""
    if name in ("cache_get", "cache_set", "create_cache"):
        from . import cache as _cache

        return getattr(_cache, name)
    if name in ("CLI_TOOL_NAMES", "SafetyContext", "get_cli_tools"):
        from . import cli_tools as _cli_tools

        return getattr(_cli_tools, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | {n for n in globals() if not n.startswith("_")})
