"""Wire-safe views of :class:`~agloom.models.ExecutionResult` for AGP streaming.

``ExecutionResult`` keeps raw LangChain message objects internally; the ``done`` event
embeds a JSON-friendly snapshot so clients are not coupled to LC ``model_dump`` shapes.
"""

from __future__ import annotations

import json
from typing import Any

from .models import ExecutionResult


def _content_to_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                bt = block.get("type")
                if bt == "text":
                    parts.append(str(block.get("text", "")))
                elif bt in ("image_url", "image"):
                    parts.append("[image]")
                else:
                    try:
                        parts.append(json.dumps(block, default=str)[:500])
                    except (TypeError, ValueError):
                        parts.append(str(block)[:500])
            else:
                parts.append(str(block))
        return "\n".join(parts)
    if isinstance(content, dict):
        try:
            return json.dumps(content, default=str)[:4000]
        except (TypeError, ValueError):
            return str(content)[:4000]
    return str(content)


def _tool_calls_summary(tool_calls: Any) -> list[dict[str, Any]] | None:
    if not tool_calls:
        return None
    out: list[dict[str, Any]] = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else None
            name = tc.get("name")
            if name is None and isinstance(fn, dict):
                name = fn.get("name")
            tid = tc.get("id")
            args = tc.get("args")
            if args is None and isinstance(fn, dict):
                args = fn.get("arguments")
            snippet = ""
            if isinstance(args, str):
                snippet = args[:400]
            elif args is not None:
                try:
                    snippet = json.dumps(args, default=str)[:400]
                except (TypeError, ValueError):
                    snippet = str(args)[:400]
            rec: dict[str, Any] = {"name": str(name or ""), "id": str(tid or "")}
            if snippet:
                rec["args_snippet"] = snippet
            out.append(rec)
        else:
            out.append({"repr": repr(tc)[:400]})
    return out or None


def chat_message_wire_dict(msg: Any) -> dict[str, Any]:
    """Serialize one ``ExecutionResult.messages`` entry for AGP ``done.result.messages``."""
    cls_name = type(msg).__name__
    if isinstance(msg, dict):
        try:
            blob = json.dumps(msg, default=str)[:4000]
        except (TypeError, ValueError):
            blob = str(msg)[:4000]
        return {"role": "dict", "content": blob, "lc_class": "dict"}

    role_raw = getattr(msg, "type", None)
    role: str
    if callable(role_raw):
        try:
            role = str(role_raw())
        except Exception:
            role = ""
    else:
        role = str(role_raw or "")
    if not role:
        role = "unknown"

    if hasattr(msg, "content"):
        text = _content_to_str(getattr(msg, "content", None))
        rec: dict[str, Any] = {"role": role, "content": text, "lc_class": cls_name}
        summary = _tool_calls_summary(getattr(msg, "tool_calls", None))
        if summary is not None:
            rec["tool_calls"] = summary
        tci = getattr(msg, "tool_call_id", None)
        if tci:
            rec["tool_call_id"] = str(tci)
        nm = getattr(msg, "name", None)
        if nm:
            rec["name"] = str(nm)
        return rec

    try:
        body = str(msg)
    except Exception:
        body = repr(msg)
    return {"role": "unknown", "content": body[:4000], "lc_class": cls_name}


def execution_result_wire_dict(result: ExecutionResult) -> dict[str, Any]:
    """JSON-serializable ``ExecutionResult`` mapping for ``AgentEvent(type='done')`` payloads."""
    payload: dict[str, Any] = json.loads(result.model_dump_json(exclude={"messages"}))
    payload["messages"] = [chat_message_wire_dict(m) for m in (result.messages or [])]
    return payload
