"""Emit ``llm_call`` AgentEvents for CLI ``metric.tokens`` — track reported usage to avoid double-counting."""

from __future__ import annotations

from typing import Any

from .models import AgentEvent, AgentStep

_WIRE_EMITTED_KEY = "_wire_emitted_tokens"


def reset_wire_emitted_usage(run_config: dict) -> None:
    """Reset per-turn token accounting at the start of ``run_fresh``."""
    run_config[_WIRE_EMITTED_KEY] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def _pick_usage_int(usage: dict[str, int], *keys: str) -> int:
    for key in keys:
        val = usage.get(key)
        if val:
            return val
    return 0


def _coerce_usage(usage: dict[str, int]) -> dict[str, int]:
    inp = _pick_usage_int(usage, "input_tokens", "prompt_tokens")
    out = _pick_usage_int(usage, "output_tokens", "completion_tokens")
    total = usage.get("total_tokens") or 0
    if not total and (inp or out):
        total = inp + out
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": total}


def emitted_usage(run_config: dict) -> dict[str, int]:
    raw = run_config.get(_WIRE_EMITTED_KEY)
    if not isinstance(raw, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return _coerce_usage(raw)


def record_emitted_usage(run_config: dict, usage: dict[str, int]) -> None:
    """Accumulate usage already pushed as ``llm_call`` on the event queue."""
    if not usage:
        return
    u = _coerce_usage(usage)
    if not any(u.values()):
        return
    cur = emitted_usage(run_config)
    ledger = run_config.setdefault(
        _WIRE_EMITTED_KEY,
        {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )
    ledger["input_tokens"] = cur["input_tokens"] + u["input_tokens"]
    ledger["output_tokens"] = cur["output_tokens"] + u["output_tokens"]
    ledger["total_tokens"] = cur["total_tokens"] + u["total_tokens"]


def _stream_usage_prefers_sum(chunk: Any) -> bool:
    """True for providers that usually emit per-chunk usage deltas (Bedrock, Vertex, …)."""
    labels: list[str] = []
    for attr in ("model_name", "model", "model_id"):
        v = getattr(chunk, attr, None)
        if isinstance(v, str) and v.strip():
            labels.append(v.strip().lower())
    meta = getattr(chunk, "response_metadata", None)
    if isinstance(meta, dict):
        for key in ("model_name", "model_id", "model"):
            v = meta.get(key)
            if isinstance(v, str) and v.strip():
                labels.append(v.strip().lower())
    blob = " ".join(labels)
    return any(
        token in blob
        for token in ("bedrock", "vertex", "gemini", "anthropic.claude", "amazon.")
    )


def accumulate_stream_usage(acc: dict[str, int], chunk: Any) -> None:
    """Merge token usage from one streamed chunk into *acc* (mutated in place).

    Providers such as Anthropic may attach **monotonic cumulative** ``usage_metadata`` on
    intermediate ``AIMessageChunk``s; the final chunk may omit fields present earlier.
    **Cumulative** providers (Anthropic, OpenAI stream totals) send non-decreasing totals — we
    take the component-wise maximum. **Delta** providers (some Bedrock/Vertex chunks) send
    per-chunk increments — when a field decreases vs the accumulator, we **add** instead.
    """
    if not chunk:
        return
    from .models import _extract_token_usage

    raw = _extract_token_usage(chunk)
    if not raw:
        return
    b = _coerce_usage(raw)
    if not any(b.values()):
        return
    if not acc:
        acc.update(b)
        return
    a = _coerce_usage(acc)
    cumulative = not _stream_usage_prefers_sum(chunk) and (
        b["input_tokens"] >= a["input_tokens"]
        and b["output_tokens"] >= a["output_tokens"]
        and (not b["total_tokens"] or not a["total_tokens"] or b["total_tokens"] >= a["total_tokens"])
    )
    acc.clear()
    if cumulative:
        acc.update(
            {
                "input_tokens": max(a["input_tokens"], b["input_tokens"]),
                "output_tokens": max(a["output_tokens"], b["output_tokens"]),
                "total_tokens": max(a["total_tokens"], b["total_tokens"]),
            }
        )
    else:
        acc.update(
            {
                "input_tokens": a["input_tokens"] + b["input_tokens"],
                "output_tokens": a["output_tokens"] + b["output_tokens"],
                "total_tokens": a["total_tokens"] + b["total_tokens"],
            }
        )


def finalize_stream_usage(acc: dict[str, int]) -> dict[str, int]:
    """Normalize accumulated stream usage (fill ``total_tokens`` when missing)."""
    u = _coerce_usage(acc)
    if not u["total_tokens"] and (u["input_tokens"] or u["output_tokens"]):
        u = {
            **u,
            "total_tokens": u["input_tokens"] + u["output_tokens"],
        }
    return u


def usage_remainder(total: dict[str, int], emitted: dict[str, int]) -> dict[str, int]:
    """Usage present in ``ExecutionResult`` but not yet emitted on the wire."""
    t = _coerce_usage(total)
    e = _coerce_usage(emitted)
    inp = max(0, t["input_tokens"] - e["input_tokens"])
    out = max(0, t["output_tokens"] - e["output_tokens"])
    tot = max(0, t["total_tokens"] - e["total_tokens"])
    if not tot and (inp or out):
        tot = inp + out
    if not inp and not out and not tot:
        return {}
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": tot}


def llm_label_from_run_config(run_config: dict) -> str | None:
    llm = run_config.get("llm")
    if llm is None:
        return None
    for attr in ("model_name", "model", "model_id"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    cls = getattr(llm, "__class__", None)
    return cls.__name__ if cls is not None else None


async def emit_llm_call_usage(
    run_config: dict,
    usage: dict[str, int],
    *,
    phase: str,
    model: str | None = None,
    name: str | None = None,
    duration_ms: float | int | None = None,
) -> None:
    """Push ``llm_call`` with ``usage`` when ``_event_queue`` is set; record as emitted."""
    queue = run_config.get("_event_queue")
    if queue is None:
        return
    u = _coerce_usage(usage)
    if not any(u.values()):
        return
    lbl = model or llm_label_from_run_config(run_config)
    effective_name = name or phase or "execution"
    await queue.put(
        AgentEvent(
            type="llm_call",
            data={
                "name": effective_name,
                "usage": u,
                "model": lbl,
                "phase": phase or "execution",
                **({"duration_ms": duration_ms} if duration_ms is not None else {}),
            },
        )
    )
    record_emitted_usage(run_config, u)


async def emit_llm_call_from_step(run_config: dict, step: AgentStep) -> None:
    """Emit one ``llm_call`` from an ``AgentStep`` (marks step metadata ``_wire_emitted``)."""
    usage_raw = step.metadata.get("usage")
    usage = usage_raw if isinstance(usage_raw, dict) else {}
    await emit_llm_call_usage(
        run_config,
        usage,
        phase=str(step.metadata.get("phase") or step.name),
        model=step.metadata.get("model") if isinstance(step.metadata.get("model"), str) else None,
        name=step.name,
        duration_ms=step.duration_ms,
    )
    step.metadata["_wire_emitted"] = True


async def emit_remaining_token_usage(
    run_config: dict,
    total_usage: dict[str, int],
    *,
    phase: str,
    model: str | None = None,
) -> None:
    """Emit worker / synthesis / pattern usage not yet reported via ``llm_call`` events."""
    remainder = usage_remainder(total_usage, emitted_usage(run_config))
    if not remainder:
        return
    eff = (phase or "execution").strip() or "execution"
    await emit_llm_call_usage(
        run_config,
        remainder,
        phase=eff,
        model=model,
        name=f"{eff}_rollup",
    )


async def emit_usage_from_llm_response(
    run_config: dict,
    response: Any,
    *,
    phase: str,
    model: str | None = None,
    duration_ms: float | int | None = None,
    stream_accumulated: dict[str, int] | None = None,
) -> dict[str, int]:
    """Extract usage from a LangChain response/chunk and emit when non-empty.

    When *stream_accumulated* is set (non-``None``), it holds usage merged from every
    ``astream`` chunk first; if still empty, falls back to *response* (e.g. last chunk).
    """
    from .models import _extract_token_usage

    usage: dict[str, int] = {}
    if stream_accumulated is not None:
        u = finalize_stream_usage(stream_accumulated)
        if any(u.values()):
            usage = u
    if not usage:
        usage = _extract_token_usage(response)
    if usage:
        await emit_llm_call_usage(
            run_config,
            usage,
            phase=phase,
            model=model,
            duration_ms=duration_ms,
        )
    return usage
