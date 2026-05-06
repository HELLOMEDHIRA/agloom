"""Structured tool results when output hits safety caps.

Industry practice (agent tool UX): avoid **silent** truncation, and avoid **empty failures** when a
preview helps the model plan next steps. Use a fixed metadata block the model sees **before** any
payload so ``complete=false`` is explicit (`complete=true` omits this block on full success).

References: explicit truncation + continuation hints for LLM tool outputs; layered trimming in
agent SDKs (e.g. preview + metadata patterns).
"""

from __future__ import annotations

from typing import Any

_META_OPEN = "[agloom:tool_result]"
_META_CLOSE = "[/agloom:tool_result]"


def render_complete(payload: str) -> str:
    """Pass-through for successful full payloads (no envelope)."""
    return payload


def render_incomplete(
    *,
    kind: str,
    metrics: dict[str, Any],
    hints: list[str],
    preview: str | None = None,
    preview_title: str = "--- preview only (incomplete; not the full tool output) ---",
) -> str:
    """Build a machine-readable incomplete result: meta first, then optional preview."""
    lines = [_META_OPEN, "complete=false", f"kind={kind}"]
    for k, v in metrics.items():
        safe_k = str(k).replace("\n", " ").replace("=", "_")
        lines.append(f"{safe_k}={v}")
    lines.append(_META_CLOSE)
    lines.append("")
    lines.append("Recovery:")
    for h in hints:
        lines.append(f"- {h}")
    if preview:
        lines.append("")
        lines.append(preview_title)
        lines.append(preview.rstrip())
    return "\n".join(lines)
