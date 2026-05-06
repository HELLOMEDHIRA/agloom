"""Provider ``tool_use_failed`` detection and retry nudges for ReAct (no UI)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

_TOOL_USE_FAILED = "tool_use_failed"

# Keys commonly seen when models emit tool intent as JSON text instead of native tool_calls.
_STRAY_TOOL_JSON_KEYS = frozenset({"type", "name", "parameters", "arguments", "function", "id"})


def human_message_after_stray_tool_json() -> str:
    """Nudge after the model put tool arguments in plain assistant text (no structured tool_calls)."""
    return (
        "Your last reply was JSON that *describes* a tool call, but this runtime only runs tools "
        "through the model's **native tool-calling channel** — not as raw JSON in the message body.\n"
        "Call the tool again using the provider's structured tool API only. "
        "After the tool result arrives, answer in normal prose (no JSON tool blobs)."
    )


def _tool_name_from_stray_dict(d: dict[str, Any]) -> str | None:
    fn = d.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()
    n = d.get("name")
    if isinstance(n, str) and n.strip():
        return n.strip()
    return None


def _stray_dict_looks_like_tool_call(d: dict[str, Any]) -> bool:
    if d.get("type") == "function":
        return True
    if "parameters" in d or "arguments" in d:
        return True
    if isinstance(d.get("function"), dict):
        return True
    if _tool_name_from_stray_dict(d) and set(d.keys()).issubset(_STRAY_TOOL_JSON_KEYS):
        return True
    return False


def last_ai_message_is_stray_tool_json(messages: list[Any], allowed_tool_names: frozenset[str]) -> bool:
    """True if the latest assistant turn is JSON tool-shaped text but has no ``tool_calls``."""
    if not allowed_tool_names or not messages:
        return False
    last = messages[-1]
    if isinstance(last, ToolMessage):
        return False
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        if getattr(msg, "tool_calls", None):
            return False
        raw = msg.content
        if not raw or not isinstance(raw, str):
            return False
        text = raw.strip()
        if not (text.startswith("{") and text.endswith("}")):
            return False
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        if not _stray_dict_looks_like_tool_call(data):
            return False
        tname = _tool_name_from_stray_dict(data)
        return bool(tname and tname in allowed_tool_names)
    return False


def exception_indicates_tool_use_failed(exc: BaseException) -> bool:
    """True when the provider rejected the model turn as invalid tool output (e.g. Groq)."""
    visited: set[int] = set()

    def _walk(err: BaseException | None) -> bool:
        if err is None:
            return False
        eid = id(err)
        if eid in visited:
            return False
        visited.add(eid)
        low = str(err).lower()
        if "tool_use_failed" in low or "failed_generation" in low:
            return True
        body = getattr(err, "body", None)
        if isinstance(body, dict):
            nested = body.get("error")
            if isinstance(nested, dict):
                if nested.get("code") == _TOOL_USE_FAILED:
                    return True
                if _TOOL_USE_FAILED in str(nested.get("message", "")).lower():
                    return True
        resp = getattr(err, "response", None)
        if resp is not None:
            json_fn = getattr(resp, "json", None)
            if callable(json_fn):
                try:
                    payload = json_fn()
                    if isinstance(payload, dict):
                        nested = payload.get("error")
                        if isinstance(nested, dict) and nested.get("code") == _TOOL_USE_FAILED:
                            return True
                except Exception:
                    pass
        cause = err.__cause__
        if cause is not None and _walk(cause):
            return True
        ctx = err.__context__
        if ctx is not None and ctx is not cause and _walk(ctx):
            return True
        return False

    return _walk(exc)


def extract_failed_generation_snippet(exc: BaseException, *, max_len: int = 320) -> str:
    """Best-effort parse of provider ``failed_generation`` text for retry hints."""
    visited: set[int] = set()

    def from_dict(d: dict) -> str:
        err = d.get("error")
        if isinstance(err, dict):
            fg = err.get("failed_generation")
            if isinstance(fg, str) and fg.strip():
                return fg.strip()[:max_len]
        return ""

    def _walk(err: BaseException | None) -> str:
        if err is None:
            return ""
        eid = id(err)
        if eid in visited:
            return ""
        visited.add(eid)
        body = getattr(err, "body", None)
        if isinstance(body, dict):
            hit = from_dict(body)
            if hit:
                return hit
        resp = getattr(err, "response", None)
        if resp is not None:
            json_fn = getattr(resp, "json", None)
            if callable(json_fn):
                try:
                    payload = json_fn()
                    if isinstance(payload, dict):
                        hit = from_dict(payload)
                        if hit:
                            return hit
                except Exception:
                    pass
        hit = _walk(err.__cause__ or None)
        if hit:
            return hit
        ctx = err.__context__
        if ctx is not None and ctx is not err.__cause__:
            return _walk(ctx)
        return ""

    return _walk(exc)


def human_message_after_tool_use_failed(exc: BaseException) -> str:
    """HumanMessage content to nudge the model after a ``tool_use_failed`` response."""
    snippet = extract_failed_generation_snippet(exc)
    parts = [
        "The API rejected your last assistant turn: it was not a valid structured **tool call**.",
        "Do **not** output plain text that claims a tool already ran (e.g. \"The file was read successfully\"). "
        "That triggers tool_use_failed on Groq.",
        "Invoke the needed tool via tool-calling only (e.g. read_file with a valid path). "
        "Wait for the tool result message, then reply with the file content or summary.",
    ]
    if snippet:
        parts.insert(
            1,
            f"Invalid style the API rejected (do not repeat): {snippet!r}",
        )
    return "\n".join(parts)
