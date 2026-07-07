"""Central transport policy for LLM and MCP connections."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..src.exception_utils import exception_indicates_transient_transport_error
from ..src.llm_utils import AsyncRateLimiter


@dataclass(frozen=True)
class TransportPolicy:
    llm_timeout: float = 120.0
    react_graph_timeout: float | None = None
    mcp_timeout: float = 30.0
    rate_limit: float | None = None
    max_transport_retries: int = 2

    def effective_graph_timeout(self) -> float:
        if self.react_graph_timeout is not None:
            return self.react_graph_timeout
        return max(self.llm_timeout * 4.0, 300.0)


class TransportManager:
    """Align timeouts, rate limits, and classify transport failures."""

    def __init__(self, policy: TransportPolicy | None = None) -> None:
        self.policy = policy or TransportPolicy()
        self._mcp_connected = False
        self._rate_limiter: AsyncRateLimiter | None = None
        if self.policy.rate_limit is not None and self.policy.rate_limit > 0:
            self._rate_limiter = AsyncRateLimiter(max_calls_per_second=self.policy.rate_limit)

    async def acquire_llm_slot(self) -> None:
        """Block until an LLM call is allowed under ``rate_limit`` policy."""
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()

    def is_transient(self, exc: BaseException) -> bool:
        return exception_indicates_transient_transport_error(exc)

    def should_retry(self, exc: BaseException, attempt: int) -> bool:
        return attempt < self.policy.max_transport_retries and self.is_transient(exc)

    def mcp_client_dict(self, server: Any) -> dict[str, Any]:
        """Build MCP server config with timeout wired through."""
        if hasattr(server, "to_client_dict"):
            d = server.to_client_dict()
        elif isinstance(server, dict):
            d = dict(server)
        else:
            d = {}
        d.setdefault("timeout", self.policy.mcp_timeout)
        return d

    def mark_mcp_connected(self) -> None:
        self._mcp_connected = True

    def invalidate_mcp(self) -> None:
        self._mcp_connected = False

    @property
    def mcp_connected(self) -> bool:
        return self._mcp_connected
