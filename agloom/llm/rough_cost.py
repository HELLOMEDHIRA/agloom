"""Heuristic USD cost when the provider omits billing metadata (not invoice-grade).

Used by the AGP runtime translator for ``metric.cost`` when usage is known but the provider
does not return a dollar amount. Bare model ids are bucketed by name (e.g. ``claude`` →
anthropic, unprefixed ``llama`` → ``meta``); explicit ``groq:…`` prefixes use Groq rates.
"""

from __future__ import annotations

# USD per 1M tokens (input, output) — order-of-magnitude hints for UX / budgets, not billing.
_RATES_PER_1M: dict[str, tuple[float, float]] = {
    "nvidia": (0.10, 0.30),
    "groq": (0.05, 0.10),
    "meta": (0.10, 0.30),  # unprefixed Llama / meta-* ids (not ``groq:``-prefixed models)
    "openai": (5.0, 15.0),
    "anthropic": (3.0, 15.0),
    "google": (0.10, 0.40),
    "google_genai": (0.10, 0.40),
    "mistral": (0.20, 0.60),
    "cohere": (0.15, 0.60),
    "xai": (3.0, 15.0),
    "deepseek": (0.25, 0.85),
    "default": (0.25, 0.50),
}


def _slug_from_bare_model_hint(mid: str) -> str | None:
    """Infer a rate bucket from an unprefixed API model id (e.g. ``claude-sonnet-4-…``, ``gpt-4o``)."""
    m = mid.lower()
    if "claude" in m or m.startswith("anthropic/"):
        return "anthropic"
    if "gemini" in m or m.startswith("google/"):
        return "google"
    if "gpt" in m or m.startswith(("o1", "o3", "o4")):
        return "openai"
    if "grok" in m or "xai" in m:
        return "xai"
    if "groq" in m or "mixtral" in m:
        return "groq"
    # Unprefixed Llama ids may be hosted on many backends; use meta rates unless ``groq:`` prefix.
    if "llama" in m or m.startswith("meta-") or m.startswith("meta/"):
        return "meta"
    if "mistral" in m or "codestral" in m or "pixtral" in m:
        return "mistral"
    if "command" in m or "c4ai" in m or "aya" in m:
        return "cohere"
    if "deepseek" in m:
        return "deepseek"
    return None


def _slug_from_model_label(model: str | None) -> str | None:
    """Map a model label (with optional ``provider:`` / ``litellm:`` prefix) to a rate bucket."""
    if not model:
        return None
    s = model.strip()
    if not s:
        return None
    if ":" in s:
        head, tail = s.split(":", 1)
        head_l = head.strip().lower()
        tail = tail.strip()
        if not tail:
            return head_l or None
        if head_l in ("lc", "init") and ":" in tail:
            _, inner = tail.split(":", 1)
            return _slug_from_model_label(inner.strip())
        if head_l == "litellm":
            if "/" in tail:
                prov, rest = tail.split("/", 1)
                if prov.strip().lower() in _RATES_PER_1M:
                    return prov.strip().lower()
                return _slug_from_bare_model_hint(rest) or _slug_from_bare_model_hint(tail)
            return _slug_from_bare_model_hint(tail)
        if head_l in _RATES_PER_1M:
            return head_l
        return _slug_from_bare_model_hint(tail) or (head_l or None)
    return _slug_from_bare_model_hint(s)


def estimate_llm_cost_usd(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Return a small positive USD estimate from token counts, or ``0.0`` when unusable."""
    ins = max(0, input_tokens)
    outs = max(0, output_tokens)
    if ins == 0 and outs == 0:
        return 0.0
    slug = _slug_from_model_label(model)
    inp_m, out_m = _RATES_PER_1M.get(slug or "", _RATES_PER_1M["default"])
    return (ins * inp_m + outs * out_m) / 1_000_000.0
