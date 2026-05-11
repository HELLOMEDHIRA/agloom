"""Session-level token / USD budget tracking for AGP ``metric.budget.*`` events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agloom.protocol.emitter import SessionEmitter

_UNSET = object()


class SessionBudgetTracker:
    """Cumulative counters vs optional limits; emits ``metric.budget.approaching`` / ``exhausted``."""

    __slots__ = (
        "token_limit",
        "cost_limit_usd",
        "_cum_tokens",
        "_cum_cost",
        "_tok_80",
        "_tok_100",
        "_cost_80",
        "_cost_100",
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

    def patch_limits(self, *, token_limit: Any = _UNSET, cost_usd: Any = _UNSET) -> None:
        """Leave a dimension unchanged by omitting it. Pass ``None`` to clear that cap."""
        if token_limit is not _UNSET:
            self.token_limit = int(token_limit) if token_limit is not None and int(token_limit) > 0 else None  # type: ignore[arg-type]
            self._tok_80 = False
            self._tok_100 = False
        if cost_usd is not _UNSET:
            self.cost_limit_usd = float(cost_usd) if cost_usd is not None and float(cost_usd) > 0 else None  # type: ignore[arg-type]
            self._cost_80 = False
            self._cost_100 = False

    def record_tokens_delta(self, emitter: SessionEmitter, *, input_tokens: int, output_tokens: int) -> None:
        if input_tokens == 0 and output_tokens == 0:
            return
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

    def is_invoke_blocked(self) -> bool:
        if self.token_limit and self.token_limit > 0 and self._cum_tokens >= self.token_limit:
            return True
        if self.cost_limit_usd and self.cost_limit_usd > 0 and self._cum_cost >= self.cost_limit_usd:
            return True
        return False

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
