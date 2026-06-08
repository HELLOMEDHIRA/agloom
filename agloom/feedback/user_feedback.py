"""Plug-and-play user feedback protocol and built-in handler implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .store import FeedbackStore

from ..logging_utils import get_logger

logger = get_logger(__name__)


@runtime_checkable
class UserFeedbackHandler(Protocol):
    """Structural protocol — implement ``on_feedback`` to plug in any handler."""

    async def on_feedback(
        self,
        run_id: str,
        rating: str,
        comment: str = "",
        correct: str = "",
        metadata: dict | None = None,
    ) -> None: ...


class NoOpFeedbackHandler:
    """Default handler — silent no-op, zero overhead."""

    async def on_feedback(
        self,
        run_id: str,
        rating: str,
        comment: str = "",
        correct: str = "",
        metadata: dict | None = None,
    ) -> None:
        pass


class LTSFeedbackHandler:
    """Persists feedback in LTS; negative ratings decay skill confidence."""

    def __init__(
        self,
        feedback_store: FeedbackStore,
        negative_ratings: set[str] | None = None,
    ) -> None:
        self._store = feedback_store
        self._negative_ratings = negative_ratings or {"negative", "wrong", "bad", "incorrect", "0", "1", "2"}

    async def on_feedback(
        self,
        run_id: str,
        rating: str,
        comment: str = "",
        correct: str = "",
        metadata: dict | None = None,
    ) -> None:
        metadata = metadata or {}
        success = await self._store.apply_user_feedback(
            run_id=run_id,
            rating=rating,
            comment=comment,
            correct=correct,
            metadata=metadata,
        )
        if not success:
            logger.warning(f"LTSFeedbackHandler: run_id '{run_id}' not found in store")


class WebhookFeedbackHandler:
    """POST feedback to an external HTTP endpoint. Reuses a single AsyncClient for connection pooling."""

    def __init__(
        self,
        url: str,
        headers: dict | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._url = url
        self._headers = {"Content-Type": "application/json", **(headers or {})}
        self._timeout = timeout
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init a reusable httpx.AsyncClient for connection pooling."""
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                headers=self._headers,
                timeout=self._timeout,
            )
        return self._client

    async def on_feedback(
        self,
        run_id: str,
        rating: str,
        comment: str = "",
        correct: str = "",
        metadata: dict | None = None,
    ) -> None:
        try:
            client = self._get_client()
            payload = {
                "run_id": run_id,
                "rating": rating,
                "comment": comment,
                "correct": correct,
                **(metadata or {}),
            }
            resp = await client.post(self._url, json=payload)
            if resp.status_code >= 400:
                logger.warning(f"WebhookFeedbackHandler: POST returned {resp.status_code} for run {run_id}")
            else:
                logger.debug(f"WebhookFeedbackHandler: POST OK {resp.status_code} for run {run_id}")
        except ImportError:
            logger.error("WebhookFeedbackHandler: httpx not installed. Run: pip install httpx")
        except Exception as e:
            logger.warning(f"WebhookFeedbackHandler: POST failed for run {run_id}: {e}")

    async def aclose(self) -> None:
        """Shut down the underlying HTTP connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class CompositeHandler:
    """Chain multiple handlers concurrently; individual failures are isolated."""

    def __init__(self, *handlers: UserFeedbackHandler) -> None:
        self._handlers = list(handlers)
        if not self._handlers:
            logger.warning("CompositeHandler: initialised with zero handlers")

    def add(self, handler: UserFeedbackHandler) -> CompositeHandler:
        """Fluent: add a handler after construction."""
        self._handlers.append(handler)
        return self

    async def on_feedback(
        self,
        run_id: str,
        rating: str,
        comment: str = "",
        correct: str = "",
        metadata: dict | None = None,
    ) -> None:
        import asyncio

        results = await asyncio.gather(
            *(h.on_feedback(run_id, rating, comment, correct, metadata) for h in self._handlers), return_exceptions=True
        )

        for i, r in enumerate(results):
            if isinstance(r, Exception):
                handler_name = type(self._handlers[i]).__name__
                logger.warning(f"CompositeHandler: {handler_name} failed for run {run_id}: {r}")


class CustomFeedbackHandlerTemplate:
    """Copy and implement on_feedback() — no base class needed."""

    async def on_feedback(
        self,
        run_id: str,
        rating: str,
        comment: str = "",
        correct: str = "",
        metadata: dict | None = None,
    ) -> None:
        raise NotImplementedError("Implement on_feedback() in your subclass")
