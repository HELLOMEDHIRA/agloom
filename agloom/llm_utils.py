"""LLM resilience: structured output retries, rate limiting, concurrency gate, circuit breaker, safe tasks."""

from __future__ import annotations

import asyncio
import json
import os
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
# Prefix allowlist for new Groq structured-output models (see Groq structured-outputs docs).
_GROQ_JSON_SCHEMA_ID_PREFIXES: tuple[str, ...] = (
    "meta-llama/llama-4",
    "llama-4-",
    "openai/gpt-oss",
    "gpt-oss",
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
    if tail in _GROQ_JSON_SCHEMA_MODEL_IDS:
        return True
    return any(key.startswith(p) for p in _GROQ_JSON_SCHEMA_ID_PREFIXES) or any(
        tail.startswith(p) for p in _GROQ_JSON_SCHEMA_ID_PREFIXES
    )


def _env_skip_json_schema_first() -> bool:
    """Opt-out of ``json_schema`` first attempt for any provider (debug / odd endpoints)."""
    v = (os.environ.get("AGLOOM_SKIP_JSON_SCHEMA") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


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


class CircuitBreakerError(RuntimeError):
    """The LLM :class:`CircuitBreaker` rejected this call (fast-fail or probe contention)."""


class CircuitBreakerOpen(CircuitBreakerError):
    """Breaker is OPEN — too many failures; cooldown not elapsed."""

    def __init__(self, *, threshold: int, recovery_s: float) -> None:
        self.threshold = threshold
        self.recovery_s = recovery_s
        super().__init__(
            f"CircuitBreaker OPEN — fast-failing after {threshold} consecutive failures. "
            f"Retry after {recovery_s}s cooldown."
        )


class CircuitBreakerHalfOpenBusy(CircuitBreakerError):
    """HALF-OPEN state; another request is already acting as the probe."""


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
    """Parse ``schema`` from ``llm`` via json_schema → tool calling → raw JSON fallback; returns None if all fail.

    Set ``AGLOOM_SKIP_JSON_SCHEMA=1`` to skip the ``json_schema`` attempt for any provider (after Groq-specific skips).
    """
    tag = f"[{caller}] " if caller else ""
    errors: list[str] = []
    skip_json_schema = _llm_skips_json_schema_mode(llm) or _env_skip_json_schema_first()

    async def _invoke_retry_half_busy(
        structured: Any,
        strategy_label: str,
    ) -> T | None:
        """Probe contention on HALF-OPEN is transient — retry with short backoff before giving up."""
        delays_s = (0.0, 0.015, 0.04, 0.1, 0.25)
        last_busy: CircuitBreakerHalfOpenBusy | None = None
        for delay in delays_s:
            if delay:
                await asyncio.sleep(delay)
            try:
                return await _try_invoke(
                    structured,
                    messages,
                    timeout,
                    rate_limiter,
                    tag,
                    strategy_label,
                    errors,
                    circuit_breaker=_circuit_breaker_for(llm),
                )
            except CircuitBreakerHalfOpenBusy as exc:
                last_busy = exc
                continue
        if last_busy is not None:
            errors.append(f"{strategy_label}: {last_busy!r}")
            logger.warning(f"{tag}{last_busy}")
        return None

    if not skip_json_schema:
        structured = _build_structured(llm, schema, method="json_schema")
        if structured is not None:
            result = await _invoke_retry_half_busy(structured, "json_schema")
            if result is not None:
                return result

    structured = _build_structured(llm, schema, method=None)
    if structured is not None:
        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
            result = await _invoke_retry_half_busy(
                structured,
                f"function_calling(attempt={attempt + 1})",
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


_structured_by_llm: weakref.WeakKeyDictionary[Any, OrderedDict[tuple[type[Any], str | None], Any]] = (
    weakref.WeakKeyDictionary()
)
_STRUCTURED_CACHE_MAX_PER_LLM = 64
_structured_by_id: OrderedDict[Any, OrderedDict[tuple[type[Any], str | None], Any]] = OrderedDict()
_MAX_ID_STRUCTURED_LLMS = 64
_cache_lock = threading.Lock()


def llm_weak_dict_key_ok(llm: Any) -> bool:
    """True when *llm* can be a ``WeakKeyDictionary`` key (hashable and weakref-able).

    LangChain chat models such as ``ChatNVIDIA`` often support ``weakref.ref`` but define
  ``__eq__`` without ``__hash__``, which raises ``TypeError: unhashable type`` on lookup.
    """
    try:
        hash(llm)
        weakref.ref(llm)
    except TypeError:
        return False
    return True


def _structured_inner_get(llm: Any) -> OrderedDict[tuple[type[Any], str | None], Any] | None:
    if llm_weak_dict_key_ok(llm):
        with _cache_lock:
            return _structured_by_llm.get(llm)
    from agloom.llm.instance_key import llm_cache_key

    with _cache_lock:
        return _structured_by_id.get(llm_cache_key(llm))


def _structured_inner_get_or_create(llm: Any) -> OrderedDict[tuple[type[Any], str | None], Any]:
    if llm_weak_dict_key_ok(llm):
        with _cache_lock:
            inner = _structured_by_llm.get(llm)
            if inner is None:
                inner = OrderedDict()
                _structured_by_llm[llm] = inner
            return inner
    from agloom.llm.instance_key import llm_cache_key

    key = llm_cache_key(llm)
    with _cache_lock:
        inner = _structured_by_id.get(key)
        if inner is None:
            if len(_structured_by_id) >= _MAX_ID_STRUCTURED_LLMS:
                _structured_by_id.popitem(last=False)
            inner = OrderedDict()
            _structured_by_id[key] = inner
        else:
            _structured_by_id.move_to_end(key)
        return inner


def _build_structured[T: BaseModel](
    llm: Any,
    schema: type[T],
    method: str | None,
) -> Any | None:
    """Build a structured LLM, returning None if the method is unsupported.

    Cached per LLM instance (weak dict when hashable, else ``id(llm)``) so GC/id reuse
    cannot return a structured runnable bound to a different model.
    """
    inner_key = (schema, method)
    inner = _structured_inner_get(llm)
    if inner is not None and inner_key in inner:
        inner.move_to_end(inner_key)
        return inner[inner_key]

    kwargs: dict[str, Any] = {"include_raw": False}
    if method is not None:
        kwargs["method"] = method
    try:
        result = llm.with_structured_output(schema, **kwargs)
    except (NotImplementedError, TypeError, ValueError):
        result = None

    inner = _structured_inner_get_or_create(llm)
    if len(inner) >= _STRUCTURED_CACHE_MAX_PER_LLM:
        inner.popitem(last=False)
    inner[inner_key] = result

    return result


def exercise_llm_weak_dict_paths(llm: Any) -> None:
    """Touch every LLM-keyed cache path (tests / provider probes). Must not raise."""
    _circuit_breaker_for(llm)

    class _ProbeSchema(BaseModel):
        ok: bool = True

    _build_structured(llm, _ProbeSchema, None)
    _build_structured(llm, _ProbeSchema, None)

    from agloom.skills.lifecycle import _compute_model_fingerprint

    _compute_model_fingerprint(llm)


async def _try_invoke[T: BaseModel](
    structured: Any,
    messages: list[BaseMessage],
    timeout: float,
    rate_limiter: AsyncRateLimiter | None,
    tag: str,
    strategy: str,
    errors: list[str],
    *,
    circuit_breaker: CircuitBreaker | None = None,
) -> T | None:
    """Single invocation attempt with timeout, rate limiting, concurrency gating, and circuit breaker."""
    breaker = circuit_breaker if circuit_breaker is not None else DEFAULT_CIRCUIT_BREAKER
    try:
        if rate_limiter:
            await rate_limiter.acquire()
        async with breaker, DEFAULT_LLM_SEMAPHORE:
            result = await asyncio.wait_for(
                structured.ainvoke(messages),
                timeout=timeout,
            )
        return result
    except asyncio.CancelledError:
        raise
    except CircuitBreakerHalfOpenBusy:
        raise
    except CircuitBreakerError as exc:
        errors.append(f"{strategy}: {exc!r}")
        logger.warning(f"{tag}{exc}")
        return None
    except RuntimeError as exc:
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
        """Approximate breaker state for observability (HALF is *eligible*, not necessarily active)."""
        if self._state == self.OPEN:
            if time.monotonic() - self._last_failure >= self._recovery:
                return self.HALF
        return self._state

    async def __aenter__(self):
        async with self._lock:
            now = time.monotonic()
            if self._state == self.OPEN:
                if now - self._last_failure < self._recovery:
                    raise CircuitBreakerOpen(threshold=self._threshold, recovery_s=self._recovery)
                self._state = self.HALF
            elif self._state == self.HALF:
                raise CircuitBreakerHalfOpenBusy(
                    "CircuitBreaker HALF-OPEN — a probe request is already in flight"
                )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is asyncio.CancelledError:
            return False
        async with self._lock:
            if exc_type is None:
                self._failures = 0
                self._state = self.CLOSED
            else:
                was_half = self._state == self.HALF
                self._failures += 1
                self._last_failure = time.monotonic()
                if was_half or self._failures >= self._threshold:
                    self._state = self.OPEN
                    if self._failures >= self._threshold:
                        logger.warning(
                            f"CircuitBreaker tripped OPEN after {self._failures} consecutive failures"
                        )
        return False


DEFAULT_CIRCUIT_BREAKER = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

_breakers_by_llm: weakref.WeakKeyDictionary[Any, CircuitBreaker] = weakref.WeakKeyDictionary()
_breakers_by_id: OrderedDict[Any, CircuitBreaker] = OrderedDict()
_MAX_ID_BREAKERS = 64
_breakers_lock = threading.Lock()


def _new_circuit_breaker() -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)


def _circuit_breaker_for_id(llm: Any) -> CircuitBreaker:
    """Fallback when ``llm`` cannot be a weak dict key (uses :func:`~agloom.llm.instance_key.llm_cache_key`)."""
    from agloom.llm.instance_key import llm_cache_key

    key = llm_cache_key(llm)
    with _breakers_lock:
        br = _breakers_by_id.get(key)
        if br is not None:
            _breakers_by_id.move_to_end(key)
            return br
        if len(_breakers_by_id) >= _MAX_ID_BREAKERS:
            _breakers_by_id.popitem(last=False)
        br = _new_circuit_breaker()
        _breakers_by_id[key] = br
        return br


def _circuit_breaker_for(llm: Any) -> CircuitBreaker:
    """Per-LLM breaker so classifier failures do not trip structured calls on other models."""
    if not llm_weak_dict_key_ok(llm):
        return _circuit_breaker_for_id(llm)
    with _breakers_lock:
        br = _breakers_by_llm.get(llm)
        if br is None:
            br = _new_circuit_breaker()
            _breakers_by_llm[llm] = br
        return br
