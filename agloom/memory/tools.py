"""Active memory tools — save/recall that agents invoke on demand.

Namespace is resolved at call-time from RunnableConfig (set by run_agent()),
so tool instances are safely shared across all threads, users, and agents.
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
    """Extract memory_namespace from config. Falls back to ephemeral ns on misconfiguration."""
    try:
        configurable = (config or {}).get("configurable", {})
        ns = configurable.get("memory_namespace")
        if ns is not None:
            return tuple(ns)
    except Exception as exc:
        logger.debug(f"_resolve_namespace config read failed: {exc!r}")

    ephemeral = ("memory", f"misconfigured_{uuid.uuid4().hex[:8]}")
    logger.error(
        "[MemoryTool] ❌ memory_namespace missing from config — "
        f"using ephemeral fallback {ephemeral}. "
        "This save/recall will NOT persist across calls. "
        "Ensure run_agent() is passing user_id or thread_id correctly."
    )
    return ephemeral


def create_memory_tools(store: LongTermStore) -> list:
    """Return [save_memory, recall_memory] tools bound to the given store."""

    @tool
    def save_memory(key: str, content: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
        """
        Save an important fact or user preference to long-term memory.

        Call this when the user shares something worth remembering across
        future sessions — their name, goals, preferences, decisions, or
        any key fact that would otherwise be lost when this conversation ends.

        Behaviour:
          - Same key → OVERWRITES the existing value (update, not duplicate).
            Use stable semantic keys so facts stay consolidated:
            "user_name", "pref_language", "goal_2026", "project_name"
          - New key  → creates a new memory entry.

        Args:
            key:     Short, stable, descriptive identifier.
                     Good:  "user_name", "pref_language", "dietary_restriction"
                     Bad:   "fact_1", "info", "memory" (too generic)
            content: The complete information as one or two sentences.
                     Good:  "The user's name is Harish."
                             "User prefers Python over JavaScript for backend work."
                     Bad:   "Harish" (too terse — loses context on retrieval)
        """
        ns = _resolve_namespace(config)
        store.store.put(ns, key, {"memory": content, "topic": key, "source": "agent"})

        logger.event(f"[MemoryTool] save_memory | ns={ns} | key={key!r} | content={content[:80]!r}")
        return f"✓ Saved [{key}]: {content}"

    @tool
    def recall_memory(query: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
        """
        Search long-term memory for information relevant to a query.

        Call this when:
          - The user asks about something that may have been shared in a
            previous session (name, preferences, ongoing projects).
          - You sense you may have stored relevant facts not visible in
            the current conversation context.
          - The passive context prefix didn't include what you need.

        Returns up to 5 most relevant memories. If nothing is found,
        returns "No relevant memories found." — do not fabricate.

        Args:
            query: Natural language description of what to recall.
                   Good:  "user's name"
                          "programming language preference"
                          "ongoing project details"
                          "dietary restrictions or allergies"
                   Bad:   "everything" (too broad — use specific queries)
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
