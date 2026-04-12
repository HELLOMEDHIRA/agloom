"""Cross-session semantic memory store wrapping any LangGraph BaseStore."""

from __future__ import annotations

import uuid
from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)


class LongTermStore:
    """Cross-session semantic memory store with two calling conventions:
    memory mode (auto-key) and skill mode (explicit key + metadata).
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    def save(
        self,
        namespace: tuple,
        memory: str = "",
        topic: str = "",
        *,
        key: str | None = None,
        value: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Memory mode: auto-uuid key. Skill mode: explicit key (upserts)."""
        if key is not None:
            val = {"memory": value or "", **(metadata or {})}
            self.store.put(namespace, key, val)
            return key
        k = str(uuid.uuid4())
        self.store.put(namespace, k, {"memory": memory, "topic": topic, "source": "agent"})
        return k

    async def asave(
        self,
        namespace: tuple,
        memory: str = "",
        topic: str = "",
        *,
        key: str | None = None,
        value: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        if key is not None:
            val = {"memory": value or "", **(metadata or {})}
            await self.store.aput(namespace, key, val)
            return key
        k = str(uuid.uuid4())
        await self.store.aput(namespace, k, {"memory": memory, "topic": topic, "source": "agent"})
        return k

    def format_context(
        self,
        namespace: tuple,
        query: str,
        limit: int = 3,
    ) -> str:
        """Semantic search + format. SYNC — InMemoryStore only."""
        try:
            results = self.store.search(namespace, query=query, limit=limit)
        except Exception as exc:
            logger.debug(f"LongTermStore.format_context search failed: {exc!r}")
            return ""
        if not results:
            return ""
        lines = ["## Long-term Memory"]
        for item in results:
            mem = item.value.get("memory", "")
            if mem:
                lines.append(f"- {mem}")
        return "\n".join(lines)

    async def aformat_context(
        self,
        namespace: tuple,
        query: str,
        limit: int = 3,
    ) -> str:
        """Async semantic search + format. Works with all store backends."""
        try:
            results = await self.store.asearch(namespace, query=query, limit=limit)
        except Exception as exc:
            logger.debug(f"LongTermStore.aformat_context search failed: {exc!r}")
            return ""
        if not results:
            return ""
        lines = ["## Long-term Memory"]
        for item in results:
            mem = item.value.get("memory", "")
            if mem:
                lines.append(f"- {mem}")
        return "\n".join(lines)

    def search(
        self,
        namespace: tuple,
        query: str = "",
        limit: int = 5,
        top_k: int | None = None,
    ) -> list:
        """Semantic search. Accepts both limit= and top_k= (alias)."""
        try:
            return self.store.search(namespace, query=query, limit=top_k or limit)
        except Exception as exc:
            logger.debug(f"LongTermStore.search failed: {exc!r}")
            return []

    async def asearch(
        self,
        namespace: tuple,
        query: str = "",
        limit: int = 5,
        top_k: int | None = None,
    ) -> list:
        """Async semantic search. Accepts both limit= and top_k= (alias)."""
        try:
            return await self.store.asearch(namespace, query=query, limit=top_k or limit)
        except Exception as exc:
            logger.debug(f"LongTermStore.asearch failed: {exc!r}")
            return []

    def delete(self, namespace: tuple, key: str) -> None:
        self.store.delete(namespace, key)

    async def adelete(self, namespace: tuple, key: str) -> None:
        await self.store.adelete(namespace, key)

    def get(self, namespace: tuple, key: str) -> Any:
        """Return the full Item (.value, .metadata). None if not found."""
        return self.store.get(namespace, key)

    async def aget(self, namespace: tuple, key: str) -> Any:
        return await self.store.aget(namespace, key)

    def get_value(self, namespace: tuple, key: str) -> Any:
        item = self.store.get(namespace, key)
        return item.value if item else None

    async def aget_value(self, namespace: tuple, key: str) -> Any:
        item = await self.store.aget(namespace, key)
        return item.value if item else None
