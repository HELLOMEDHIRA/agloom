"""Long-term memory tools ``save_memory`` and ``recall_memory``.

Namespace comes from ``RunnableConfig["configurable"]["memory_namespace"]``, set by
``UnifiedAgent.resolve_ids`` / compatible runners. If it is missing, an ephemeral
namespace is used and persistence will not match real sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolArg

from ..logging_utils import get_logger

if TYPE_CHECKING:
    from .store import LongTermStore

logger = get_logger(__name__)

_FALLBACK_NS: tuple[str, ...] = ("memory", "default")


def _resolve_namespace(config: RunnableConfig | None) -> tuple[tuple[str, ...], bool]:
    """Return ``(memory_namespace, is_ephemeral)``.

    When *is_ephemeral* is True, the namespace is unique per call; writes are not
    durable across agent invocations unless the runner fixes ``configurable`` wiring.
    """
    try:
        configurable = (config or {}).get("configurable", {})
        ns = configurable.get("memory_namespace")
        if ns is not None:
            return tuple(ns), False
    except Exception as exc:
        logger.debug(f"_resolve_namespace config read failed: {exc!r}")

    logger.error(
        "[MemoryTool] memory_namespace missing from RunnableConfig — "
        f"using fallback namespace {_FALLBACK_NS}. Saves will not persist across calls "
        "unless the caller sets configurable.memory_namespace (e.g. via UnifiedAgent)."
    )
    return _FALLBACK_NS, True


def create_memory_tools(store: LongTermStore) -> list:
    """Return ``save_memory`` and ``recall_memory`` bound to *store*.

    Tools are sync functions; LangChain runs them in a worker thread, so LangGraph
    ``AsyncSqliteStore`` sync ``put``/``search`` (which marshal back to the store loop) stay valid.
    Pure-async callers should use ``LongTermStore.asave`` / ``asearch`` instead of these tools.
    """

    @tool
    def save_memory(key: str, content: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
        """Store one fact under ``key`` in long-term memory (overwrites an existing ``key``).

        Use stable keys (e.g. ``user_name``, ``project_goal``) and one or two sentences in
        ``content`` so retrieval stays meaningful.
        """
        ns, ephemeral = _resolve_namespace(config)
        store.store.put(ns, key, {"memory": content, "topic": key, "source": "agent"})

        logger.event(f"[MemoryTool] save_memory | ns={ns} | key={key!r} | content={content[:80]!r}")
        if ephemeral:
            return (
                "⚠ Stored in a non-persistent memory namespace (memory_namespace missing from "
                f"RunnableConfig); this will not survive the next agent run. [{key}]: {content}"
            )
        return f"✓ Saved [{key}]: {content}"

    @tool
    def recall_memory(query: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
        """Search long-term memory for ``query``; returns up to five matches or a no-results message.

        Do not invent facts when nothing is returned.
        """
        ns, _ephemeral = _resolve_namespace(config)
        results = store.search(ns, query, limit=5)

        if not results:
            logger.debug(f"[MemoryTool] recall_memory | ns={ns} | query={query!r} → 0 results")
            msg = "No relevant memories found."
            if _ephemeral:
                return f"⚠ (non-persistent memory namespace) {msg}"
            return msg

        lines = []
        for i, item in enumerate(results):
            mem = item.value.get("memory", "") if hasattr(item, "value") else str(item)
            if mem:
                lines.append(f"[{i + 1}] {mem}")
        response = "Recalled memories:\n" + "\n".join(lines) if lines else "No relevant memories found."

        logger.event(f"[MemoryTool] recall_memory | ns={ns} | query={query!r} → {len(results)} result(s)")
        if _ephemeral:
            return f"⚠ (non-persistent memory namespace) {response}"
        return response

    return [save_memory, recall_memory]
