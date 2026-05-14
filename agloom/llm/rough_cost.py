"""Heuristic USD cost when the provider omits billing metadata (not invoice-grade)."""

from __future__ import annotations

# USD per 1M tokens (input, output) — order-of-magnitude hints for UX / budgets only.
_RATES_PER_1M: dict[str, tuple[float, float]] = {
    "nvidia": (0.10, 0.25),
    "groq": (0.05, 0.08),
    "openai": (2.50, 10.0),
    "anthropic": (3.00, 15.0),
    "google": (0.125, 0.375),
    "google_genai": (0.125, 0.375),
    "mistral": (0.20, 0.60),
    "cohere": (0.15, 0.60),
    "xai": (3.00, 15.0),
    "default": (0.20, 0.40),
}


def _slug_from_model_label(model: str | None) -> str | None:
    if not model:
        return None
    s = str(model).strip()
    if ":" in s:
        return s.split(":", 1)[0].strip().lower() or None
    return None


def estimate_llm_cost_usd(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Return a small positive USD estimate from token counts, or ``0.0`` when unusable."""
    ins = max(0, int(input_tokens))
    outs = max(0, int(output_tokens))
    if ins == 0 and outs == 0:
        return 0.0
    slug = _slug_from_model_label(model)
    inp_m, out_m = _RATES_PER_1M.get(slug or "", _RATES_PER_1M["default"])
    return (ins * inp_m + outs * out_m) / 1_000_000.0
