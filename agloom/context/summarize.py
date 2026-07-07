"""Structured episodic summarization for Context Plane."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..src.logging_utils import get_logger

logger = get_logger(__name__)

_SUMMARY_MARKER = "[SUMMARY]"

_EPISODIC_PROMPT = (
    "Summarize the following conversation turns into a structured episodic summary.\n"
    "Preserve: decisions, open questions, artifact/tool references, key facts and IDs.\n"
    "Omit: greetings, filler, redundant re-statements.\n"
    "Return plain prose (no JSON).\n\n"
    "Turns:\n{turns_text}\n\nSummary:"
)

_PLANE_PROMPT = (
    "Compress the following memory context to fit a smaller token budget.\n"
    "Preserve decisions, facts, names, IDs, and pending tasks. Omit filler.\n\n"
    "{text}\n\nCompressed:"
)


class EpisodicSummary(BaseModel):
    scope: Literal["session", "harness", "job"] = "session"
    job_id: str = ""
    harness_task_ids: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    covered_step_range: tuple[int, int] | None = None
    content_hash: str = ""


def content_hash_for_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _prepare_summarizer(model: Any) -> Any:
    """Bind temperature=0 when the model supports ``bind``."""
    if model is None:
        return None
    bind = getattr(model, "bind", None)
    if callable(bind):
        try:
            return bind(temperature=0)
        except Exception:
            pass
    return model


def refs_preserved_in_summary(
    source_refs: list[str],
    *,
    summary_text: str,
    artifact_refs: list[str],
) -> bool:
    """Return True when every extracted ref appears in summary text or artifact_refs."""
    if not source_refs:
        return True
    haystack = f"{summary_text}\n" + "\n".join(artifact_refs)
    return all(ref in haystack for ref in source_refs)


def merge_artifact_refs(existing: list[str], new_refs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ref in [*existing, *new_refs]:
        if ref and ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def episodic_summary_from_turns(
    turns: list[dict[str, Any]],
    *,
    summary_text: str,
    scope: Literal["session", "harness", "job"] = "session",
    artifact_refs: list[str] | None = None,
) -> EpisodicSummary:
    payload = json.dumps(turns, sort_keys=True, default=str)
    return EpisodicSummary(
        scope=scope,
        decisions=[summary_text[:2000]] if summary_text else [],
        artifact_refs=artifact_refs or [],
        content_hash=content_hash_for_text(payload + summary_text),
    )


def _turns_to_text(turns: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for t in turns:
        q = t.get("q", "")
        a = t.get("a", "")
        if q == _SUMMARY_MARKER:
            lines.append(f"[prior summary] {a}")
        else:
            lines.append(f"User: {q}")
            lines.append(f"Assistant: {a}")
    return "\n".join(lines)


def _extract_refs_from_turns(turns: list[dict[str, Any]]) -> list[str]:
    import re

    refs: list[str] = []
    blob = json.dumps(turns, default=str)
    for m in re.finditer(r"ref=([a-f0-9]{8,16})", blob):
        refs.append(m.group(1))
    return merge_artifact_refs([], refs)


async def summarize_oldest_turns(
    turns: list[dict[str, Any]],
    *,
    summarizer_model: Any,
    split_ratio: float = 0.7,
    min_turns: int = 4,
    scope: Literal["session", "harness", "job"] = "session",
) -> tuple[list[dict[str, Any]], EpisodicSummary | None]:
    """Compress oldest turns into one summary turn; return episodic metadata."""
    if summarizer_model is None or len(turns) < min_turns:
        return turns, None

    split_idx = max(1, int(len(turns) * split_ratio))
    oldest = turns[:split_idx]
    recent = turns[split_idx:]
    prompt = _EPISODIC_PROMPT.format(turns_text=_turns_to_text(oldest))
    model = _prepare_summarizer(summarizer_model)

    try:
        from langchain_core.messages import HumanMessage

        t0 = time.perf_counter()
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        content = getattr(resp, "content", resp)
        summary = content if isinstance(content, str) else str(content)
        summary = summary.strip()
        dur_ms = round((time.perf_counter() - t0) * 1000, 1)
        refs = _extract_refs_from_turns(oldest)
        if not refs_preserved_in_summary(refs, summary_text=summary, artifact_refs=refs):
            logger.warning("[ContextPlane] episodic summary missing artifact refs — keeping refs in metadata")
        episodic = episodic_summary_from_turns(oldest, summary_text=summary, scope=scope, artifact_refs=refs)
        summary_turn = {"q": _SUMMARY_MARKER, "a": summary, "p": "summary", "episodic": episodic.model_dump()}
        logger.info(
            f"[ContextPlane] summarized {len(oldest)} turns -> 1 summary in {dur_ms}ms "
            f"(kept {len(recent)} recent)"
        )
        return [summary_turn] + recent, episodic
    except Exception as exc:
        logger.warning(f"[ContextPlane] episodic summarize failed ({exc!r}) — keeping turns")
        return turns, None


def summarize_oldest_turns_sync(
    turns: list[dict[str, Any]],
    *,
    summarizer_model: Any,
    split_ratio: float = 0.7,
    min_turns: int = 4,
    scope: Literal["session", "harness", "job"] = "session",
) -> tuple[list[dict[str, Any]], EpisodicSummary | None]:
    if summarizer_model is None or len(turns) < min_turns:
        return turns, None

    split_idx = max(1, int(len(turns) * split_ratio))
    oldest = turns[:split_idx]
    recent = turns[split_idx:]
    prompt = _EPISODIC_PROMPT.format(turns_text=_turns_to_text(oldest))
    model = _prepare_summarizer(summarizer_model)

    try:
        from langchain_core.messages import HumanMessage

        invoke = getattr(model, "invoke", None)
        if not callable(invoke):
            return turns, None
        resp = invoke([HumanMessage(content=prompt)])
        content = getattr(resp, "content", resp)
        summary = content if isinstance(content, str) else str(content)
        summary = summary.strip()
        refs = _extract_refs_from_turns(oldest)
        if not refs_preserved_in_summary(refs, summary_text=summary, artifact_refs=refs):
            logger.warning("[ContextPlane] sync episodic summary missing artifact refs")
        episodic = episodic_summary_from_turns(oldest, summary_text=summary, scope=scope, artifact_refs=refs)
        summary_turn = {"q": _SUMMARY_MARKER, "a": summary, "p": "summary", "episodic": episodic.model_dump()}
        return [summary_turn] + recent, episodic
    except Exception as exc:
        logger.warning(f"[ContextPlane] sync episodic summarize failed ({exc!r})")
        return turns, None


async def summarize_text_for_budget(text: str, *, summarizer_model: Any) -> str:
    """Shrink prose context when over token budget (no tail chop)."""
    if not text or summarizer_model is None:
        return text
    prompt = _PLANE_PROMPT.format(text=text[:120_000])
    model = _prepare_summarizer(summarizer_model)
    try:
        from langchain_core.messages import HumanMessage

        resp = await model.ainvoke([HumanMessage(content=prompt)])
        content = getattr(resp, "content", resp)
        return content if isinstance(content, str) else str(content)
    except Exception as exc:
        logger.warning(f"[ContextPlane] text summarize failed ({exc!r})")
        return text
