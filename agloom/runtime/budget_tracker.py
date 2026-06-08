"""Session-level token / USD budget tracking for AGP ``metric.budget.*`` events."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agloom.protocol.emitter import SessionEmitter

_UNSET = object()


def _positive_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _positive_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


class SessionBudgetTracker:
    """Cumulative counters vs optional limits; emits ``metric.budget.approaching`` / ``exhausted``.

    **Advisory only for in-flight work:** caps apply at *invoke* start
    (:meth:`is_invoke_blocked`). An invocation already running is not forcibly stopped when the
    cumulative counter crosses the limit mid-turn — wire events still reflect exhaustion for the
    next turn.
    """

    __slots__ = (
        "token_limit",
        "cost_limit_usd",
        "_cum_tokens",
        "_cum_cost",
        "_tok_80",
        "_tok_100",
        "_cost_80",
        "_cost_100",
        "_lock",
        "_async_lock",
    )

    def __init__(
        self,
        *,
        token_limit: int | None = None,
        cost_limit_usd: float | None = None,
    ) -> None:
        self.token_limit = token_limit if (token_limit is not None and token_limit > 0) else None
        self.cost_limit_usd = cost_limit_usd if (cost_limit_usd is not None and cost_limit_usd > 0) else None
        self._cum_tokens = 0
        self._cum_cost = 0.0
        self._tok_80 = False
        self._tok_100 = False
        self._cost_80 = False
        self._cost_100 = False
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    def patch_limits(self, *, token_limit: Any = _UNSET, cost_usd: Any = _UNSET) -> None:
        """Leave a dimension unchanged by omitting it. Pass ``None`` to clear that cap."""
        if token_limit is not _UNSET:
            self.token_limit = _positive_int_or_none(token_limit)
            self._tok_80 = False
            self._tok_100 = False
        if cost_usd is not _UNSET:
            self.cost_limit_usd = _positive_float_or_none(cost_usd)
            self._cost_80 = False
            self._cost_100 = False

    def record_tokens_delta(self, emitter: SessionEmitter, *, input_tokens: int, output_tokens: int) -> None:
        if input_tokens == 0 and output_tokens == 0:
            return
        with self._lock:
            self._cum_tokens += input_tokens + output_tokens
            lim = self.token_limit
            if lim is None or lim <= 0:
                return
            ratio = self._cum_tokens / float(lim)
            if ratio >= 1.0 and not self._tok_100:
                self._tok_100 = True
                emitter.emit_metric_budget_exhausted(
                    dimension="tokens",
                    used=float(self._cum_tokens),
                    limit=float(lim),
                )
            elif ratio >= 0.8 and not self._tok_80:
                self._tok_80 = True
                emitter.emit_metric_budget_approaching(
                    dimension="tokens",
                    used=float(self._cum_tokens),
                    limit=float(lim),
                    ratio=ratio,
                )

    def record_cost_delta(self, emitter: SessionEmitter, *, cost: float) -> None:
        if cost <= 0.0:
            return
        with self._lock:
            self._cum_cost += cost
            lim = self.cost_limit_usd
            if lim is None or lim <= 0:
                return
            ratio = self._cum_cost / lim
            if ratio >= 1.0 and not self._cost_100:
                self._cost_100 = True
                emitter.emit_metric_budget_exhausted(
                    dimension="cost_usd",
                    used=self._cum_cost,
                    limit=lim,
                )
            elif ratio >= 0.8 and not self._cost_80:
                self._cost_80 = True
                emitter.emit_metric_budget_approaching(
                    dimension="cost_usd",
                    used=self._cum_cost,
                    limit=lim,
                    ratio=ratio,
                )

    def _is_invoke_blocked_unlocked(self) -> bool:
        if self.token_limit and self.token_limit > 0 and self._cum_tokens >= self.token_limit:
            return True
        if self.cost_limit_usd and self.cost_limit_usd > 0 and self._cum_cost >= self.cost_limit_usd:
            return True
        return False

    def is_invoke_blocked(self) -> bool:
        with self._lock:
            return self._is_invoke_blocked_unlocked()

    async def reserve_invoke_slot(self) -> bool:
        """Atomically reject a new invoke when the session budget is already exhausted."""
        async with self._async_lock:
            with self._lock:
                return not self._is_invoke_blocked_unlocked()

    @property
    def cumulative_tokens(self) -> int:
        return self._cum_tokens

    @property
    def cumulative_cost_usd(self) -> float:
        return self._cum_cost

    def snapshot(self) -> dict[str, Any]:
        return {
            "token_limit": self.token_limit,
            "cost_limit_usd": self.cost_limit_usd,
            "cumulative_tokens": self._cum_tokens,
            "cumulative_cost_usd": self._cum_cost,
            "blocked": self.is_invoke_blocked(),
        }
