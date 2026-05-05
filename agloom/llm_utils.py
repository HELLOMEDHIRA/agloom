"""LLM resilience: structured output retries, rate limiting, concurrency gate, circuit breaker, safe tasks."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import weakref
from collections import OrderedDict
from collections.abc import Coroutine
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from .logging_utils import get_logger

logger = get_logger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

# Groq: only some models accept ``response_format`` with ``json_schema`` (Structured Outputs).
# See https://console.groq.com/docs/structured-outputs#supported-models — expand when Groq adds models.
_GROQ_JSON_SCHEMA_MODEL_IDS: frozenset[str] = frozenset(
    {
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama-4-scout-17b-16e-instruct",
        "openai/gpt-oss-20b",
        "gpt-oss-20b",
        "openai/gpt-oss-120b",
        "gpt-oss-120b",
        "openai/gpt-oss-safeguard-20b",
        "gpt-oss-safeguard-20b",
    }
)


def _is_groq_chat_llm(llm: Any) -> bool:
    cls = type(llm)
    name = getattr(cls, "__name__", "")
    mod = getattr(cls, "__module__", "") or ""
    return name == "ChatGroq" or mod.startswith("langchain_groq")


def _groq_model_id(llm: Any) -> str | None:
    mid = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    if mid is None:
        return None
    if isinstance(mid, str):
        return mid.strip()
    return str(mid).strip()


def _groq_allows_json_schema_first(llm: Any) -> bool:
    """True only for Groq models documented as supporting Structured Outputs / json_schema."""
    mid = _groq_model_id(llm)
    if not mid:
        return False
    key = mid.lower()
    if key in _GROQ_JSON_SCHEMA_MODEL_IDS:
        return True
    tail = key.split("/")[-1]
    return tail in _GROQ_JSON_SCHEMA_MODEL_IDS


def _llm_skips_json_schema_mode(llm: Any) -> bool:
    """Skip ``json_schema`` when the provider+model rejects it (e.g. Groq Llama 3.3)."""
    if not _is_groq_chat_llm(llm):
        return False
    return not _groq_allows_json_schema_first(llm)


class LLMSemaphore:
    """Lazy ``asyncio.Semaphore`` limiting concurrent LLM calls (per event loop).

    asyncio primitives are bound to the event loop they are created in. Since agloom
    can be used across multiple loops (e.g. tests, threads, sync wrappers), we keep
    a semaphore per running loop to avoid "bound to a different event loop" errors.
    """

    def __init__(self, max_concurrent: int = 10) -> None:
        self._max = max_concurrent
        self._sems: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
            weakref.WeakKeyDictionary()
        )
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with self._lock:
            sem = self._sems.get(loop)
            if sem is None:
                sem = asyncio.Semaphore(self._max)
                self._sems[loop] = sem
            return sem

    async def __aenter__(self):
        await self._ensure().acquire()
        return self

    async def __aexit__(self, *_):
        self._ensure().release()


DEFAULT_LLM_SEMAPHORE = LLMSemaphore(max_concurrent=10)


async def robust_structured_call[T: BaseModel](
    llm: Any,
    schema: type[T],
    messages: list[BaseMessage],
    *,
    max_retries: int = 2,
    timeout: float = 30.0,
    rate_limiter: AsyncRateLimiter | None = None,
    caller: str = "",
) -> T | None:
    """Parse ``schema`` from ``llm`` via json_schema → tool calling → raw JSON fallback; returns None if all fail."""
    tag = f"[{caller}] " if caller else ""
    errors: list[str] = []
    skip_json_schema = _llm_skips_json_schema_mode(llm)

    if not skip_json_schema:
        structured = _build_structured(llm, schema, method="json_schema")
        if structured is not None:
            result = await _try_invoke(
                structured,
                messages,
                timeout,
                rate_limiter,
                tag,
                "json_schema",
                errors,
            )
            if result is not None:
                return result

    structured = _build_structured(llm, schema, method=None)
    if structured is not None:
        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
            result = await _try_invoke(
                structured,
                messages,
                timeout,
                rate_limiter,
                tag,
                f"function_calling(attempt={attempt + 1})",
                errors,
            )
            if result is not None:
                return result

    result = await _try_raw_json_fallback(
        llm,
        schema,
        messages,
        timeout,
        rate_limiter,
        tag,
        errors,
    )
    if result is not None:
        return result

    logger.warning(f"{tag}robust_structured_call exhausted all strategies for {schema.__name__}. Errors: {errors}")
    return None


_structured_cache: OrderedDict[tuple, Any] = OrderedDict()
_STRUCTURED_CACHE_MAX = 64
_cache_lock = threading.Lock()


def _build_structured[T: BaseModel](
    llm: Any,
    schema: type[T],
    method: str | None,
) -> Any | None:
    """Build a structured LLM, returning None if the method is unsupported. LRU-cached (max 64)."""
    cache_key = (id(llm), schema, method)
    with _cache_lock:
        if cache_key in _structured_cache:
            _structured_cache.move_to_end(cache_key)
            return _structured_cache[cache_key]

        if len(_structured_cache) >= _STRUCTURED_CACHE_MAX:
            _structured_cache.popitem(last=False)

    kwargs: dict[str, Any] = {"include_raw": False}
    if method is not None:
        kwargs["method"] = method
    try:
        result = llm.with_structured_output(schema, **kwargs)
        with _cache_lock:
            _structured_cache[cache_key] = result
        return result
    except (NotImplementedError, TypeError, ValueError):
        with _cache_lock:
            _structured_cache[cache_key] = None
        return None


async def _try_invoke[T: BaseModel](
    structured: Any,
    messages: list[BaseMessage],
    timeout: float,
    rate_limiter: AsyncRateLimiter | None,
    tag: str,
    strategy: str,
    errors: list[str],
) -> T | None:
    """Single invocation attempt with timeout, rate limiting, concurrency gating, and circuit breaker."""
    try:
        if rate_limiter:
            await rate_limiter.acquire()
        async with DEFAULT_CIRCUIT_BREAKER, DEFAULT_LLM_SEMAPHORE:
            result = await asyncio.wait_for(
                structured.ainvoke(messages),
                timeout=timeout,
            )
        return result
    except RuntimeError as exc:
        if "CircuitBreaker" in str(exc):
            errors.append(f"{strategy}: {exc!r}")
            logger.warning(f"{tag}{exc}")
            return None
        errors.append(f"{strategy}: {exc!r}")
        logger.debug(f"{tag}structured_call ({strategy}) failed: {exc!r}")
        return None
    except Exception as exc:
        errors.append(f"{strategy}: {exc!r}")
        logger.debug(f"{tag}structured_call ({strategy}) failed: {exc!r}")
        return None


async def _try_raw_json_fallback[T: BaseModel](
    llm: Any,
    schema: type[T],
    messages: list[BaseMessage],
    timeout: float,
    rate_limiter: AsyncRateLimiter | None,
    tag: str,
    errors: list[str],
) -> T | None:
    """Last-resort: call LLM for plain text, extract JSON, parse with Pydantic."""
    try:
        json_instruction = SystemMessage(
            content=(
                f"Respond ONLY with a valid JSON object matching this schema. "
                f"No markdown fences, no explanation, just raw JSON.\n"
                f"Schema fields: {list(schema.model_fields.keys())}"
            )
        )
        augmented = [json_instruction] + list(messages)

        if rate_limiter:
            await rate_limiter.acquire()
        async with DEFAULT_LLM_SEMAPHORE:
            raw_resp = await asyncio.wait_for(
                llm.ainvoke(augmented),
                timeout=timeout,
            )
        text = raw_resp.content if hasattr(raw_resp, "content") else str(raw_resp)
        parsed = _extract_and_parse(text, schema)
        if parsed is not None:
            logger.debug(f"{tag}raw JSON fallback succeeded for {schema.__name__}")
            return parsed
        errors.append("raw_json: no valid JSON found in response")
    except Exception as exc:
        errors.append(f"raw_json: {exc!r}")
        logger.debug(f"{tag}raw JSON fallback failed: {exc!r}")
    return None


def _extract_and_parse[T: BaseModel](text: str, schema: type[T]) -> T | None:
    """Extract JSON from fenced blocks or bare objects and parse into schema."""
    candidates: list[str] = []

    for m in _JSON_BLOCK_RE.finditer(text):
        candidates.append(m.group(1).strip())

    for m in _JSON_OBJECT_RE.finditer(text):
        candidates.append(m.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


class AsyncRateLimiter:
    """
    Token-bucket rate limiter for LLM API calls.

    Usage:
        limiter = AsyncRateLimiter(max_calls_per_second=10.0)
        await limiter.acquire()  # blocks if over budget
    """

    def __init__(self, max_calls_per_second: float = 10.0) -> None:
        self._interval = 1.0 / max_calls_per_second
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._last_call = time.monotonic()


def _task_exception_callback(task: asyncio.Task) -> None:
    """Log exceptions from background tasks instead of swallowing them."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning(f"Background task {task.get_name()!r} failed: {exc!r}")


def safe_create_task(
    coro: Coroutine,
    *,
    name: str | None = None,
) -> asyncio.Task:
    """create_task() with automatic exception logging on failure."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_task_exception_callback)
    return task


class CircuitBreaker:
    """
    Fast-fail gate for LLM API calls.

    States:
      CLOSED  → normal operation, requests pass through
      OPEN    → all requests fail immediately (fast-fail)
      HALF    → one probe request allowed; success → CLOSED, failure → OPEN

    Transitions:
      CLOSED  → OPEN   after `failure_threshold` consecutive failures
      OPEN    → HALF   after `recovery_timeout` seconds
      HALF    → CLOSED on first success
      HALF    → OPEN   on first failure
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._recovery = recovery_timeout
        self._state = self.CLOSED
        self._failures = 0
        self._last_failure = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if time.monotonic() - self._last_failure >= self._recovery:
                return self.HALF
        return self._state

    async def __aenter__(self):
        async with self._lock:
            current = self.state
            if current == self.OPEN:
                raise RuntimeError(
                    f"CircuitBreaker OPEN — fast-failing after "
                    f"{self._threshold} consecutive failures. "
                    f"Retry after {self._recovery}s cooldown."
                )
            if current == self.HALF:
                self._state = self.HALF
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        async with self._lock:
            if exc_type is None:
                self._failures = 0
                self._state = self.CLOSED
            else:
                self._failures += 1
                self._last_failure = time.monotonic()
                if self._failures >= self._threshold:
                    self._state = self.OPEN
                    logger.warning(f"CircuitBreaker tripped OPEN after {self._failures} consecutive failures")
        return False


DEFAULT_CIRCUIT_BREAKER = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
