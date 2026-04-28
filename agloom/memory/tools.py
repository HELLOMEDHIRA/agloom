"""Long-term memory tools ``save_memory`` and ``recall_memory``.

Namespace comes from ``RunnableConfig["configurable"]["memory_namespace"]``, set by
``UnifiedAgent.resolve_ids`` / compatible runners. If it is missing, an ephemeral
namespace is used and persistence will not match real sessions.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolArg

from ..logging_utils import get_logger

if TYPE_CHECKING:
    from .store import LongTermStore

logger = get_logger(__name__)

_FALLBACK_NS: tuple[str, ...] = ("memory", "default")


def _resolve_namespace(config: RunnableConfig | None) -> tuple[str, ...]:
    """Return ``memory_namespace`` from config, or a one-off fallback if absent."""
    try:
        configurable = (config or {}).get("configurable", {})
        ns = configurable.get("memory_namespace")
        if ns is not None:
            return tuple(ns)
    except Exception as exc:
        logger.debug(f"_resolve_namespace config read failed: {exc!r}")

    ephemeral = ("memory", f"misconfigured_{uuid.uuid4().hex[:8]}")
    logger.error(
        "[MemoryTool] memory_namespace missing from RunnableConfig — "
        f"using ephemeral namespace {ephemeral}. Saves will not persist across calls "
        "unless the caller sets configurable.memory_namespace (e.g. via UnifiedAgent)."
    )
    return ephemeral


def create_memory_tools(store: LongTermStore) -> list:
    """Build ``save_memory`` and ``recall_memory`` tools bound to ``store``."""

    @tool
    def save_memory(key: str, content: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
        """Store one fact under ``key`` in long-term memory (overwrites an existing ``key``).

        Use stable keys (e.g. ``user_name``, ``project_goal``) and one or two sentences in
        ``content`` so retrieval stays meaningful.
        """
        ns = _resolve_namespace(config)
        store.store.put(ns, key, {"memory": content, "topic": key, "source": "agent"})

        logger.event(f"[MemoryTool] save_memory | ns={ns} | key={key!r} | content={content[:80]!r}")
        return f"✓ Saved [{key}]: {content}"

    @tool
    def recall_memory(query: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
        """Search long-term memory for ``query``; returns up to five matches or a no-results message.

        Do not invent facts when nothing is returned.
        """
        ns = _resolve_namespace(config)
        results = store.search(ns, query, limit=5)

        if not results:
            logger.debug(f"[MemoryTool] recall_memory | ns={ns} | query={query!r} → 0 results")
            return "No relevant memories found."

        lines = []
        for i, item in enumerate(results):
            mem = item.value.get("memory", "") if hasattr(item, "value") else str(item)
            if mem:
                lines.append(f"[{i + 1}] {mem}")
        response = "Recalled memories:\n" + "\n".join(lines) if lines else "No relevant memories found."

        logger.event(f"[MemoryTool] recall_memory | ns={ns} | query={query!r} → {len(results)} result(s)")
        return response

    return [save_memory, recall_memory]
