"""Context window inference and output reservation."""

from __future__ import annotations

import re
from typing import Any

from ..llm.chat_template_compat import extract_model_label

_DEFAULT_CONTEXT_WINDOW = 128_000
_MAX_OUTPUT_FRACTION = 0.12
_OUTPUT_CAP = 8192


def _parse_int_from_label(label: str) -> int | None:
    low = label.lower()
    m = re.search(r"\b(\d{2,3})k\b", low)
    if m:
        return int(m.group(1)) * 1024
    for token in ("131072", "128000", "200000", "100000", "32768", "16384", "8192"):
        if token in low.replace("_", ""):
            return int(token)
    return None


def infer_context_window_tokens(llm: Any, model_spec: Any = None) -> int:
    """Best-effort context window for budgeting (not output ``max_tokens``)."""
    hints: list[str] = []
    if isinstance(model_spec, str) and model_spec.strip():
        hints.append(model_spec.strip())
    hints.append(extract_model_label(llm))
    for node in (llm,):
        for attr in (
            "context_window",
            "max_context_tokens",
            "max_input_tokens",
            "model_max_length",
        ):
            v = getattr(node, attr, None)
            if isinstance(v, int) and v > 0:
                return v
        mk = getattr(node, "model_kwargs", None)
        if isinstance(mk, dict):
            for key in ("context_window", "max_input_tokens", "max_context_tokens"):
                raw = mk.get(key)
                if isinstance(raw, int) and raw > 0:
                    return raw
    for hint in hints:
        parsed = _parse_int_from_label(hint)
        if parsed is not None:
            return parsed
        low = hint.lower()
        if "qwen" in low or "qwq" in low:
            return 131_072
    return _DEFAULT_CONTEXT_WINDOW


def reserved_output_tokens(
    llm: Any,
    *,
    context_window: int,
    configured_max_tokens: int | None = None,
    enable_thinking: bool | None = None,
) -> int:
    """Tokens reserved for model output so input budgeting stays safe."""
    candidates: list[int] = []
    if isinstance(configured_max_tokens, int) and configured_max_tokens > 0:
        candidates.append(configured_max_tokens)
    for attr in ("max_tokens", "max_output_tokens"):
        v = getattr(llm, attr, None)
        if isinstance(v, int) and v > 0:
            candidates.append(v)
    mk = getattr(llm, "model_kwargs", None)
    if isinstance(mk, dict):
        raw = mk.get("max_tokens")
        if isinstance(raw, int) and raw > 0:
            candidates.append(raw)
    if not candidates:
        reserved = min(_OUTPUT_CAP, max(1024, int(context_window * 0.06)))
    else:
        requested = max(candidates)
        cap = max(1024, int(context_window * _MAX_OUTPUT_FRACTION))
        reserved = min(requested, cap, _OUTPUT_CAP)
    if enable_thinking is True:
        thinking_extra = max(4096, int(context_window * 0.05))
        cap = max(1024, int(context_window * _MAX_OUTPUT_FRACTION))
        reserved = min(reserved + thinking_extra, cap)
    return reserved
