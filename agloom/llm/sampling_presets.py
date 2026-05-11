"""Provider-oriented sampling defaults and typical ranges for session metadata (no wire secrets)."""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from agloom.llm.llm_provider_params import normalize_provider_slug
from agloom.llm.model_resolver import split_provider_prefix


def infer_provider_slug_from_args(args: Namespace) -> str | None:
    """Best-effort slug from ``--provider`` or ``provider:`` model prefix (else ``None``)."""
    prov = getattr(args, "provider", None)
    if isinstance(prov, str) and prov.strip():
        return normalize_provider_slug(prov.strip())
    mid = getattr(args, "model", None)
    if isinstance(mid, str) and mid.strip():
        pref, _rest = split_provider_prefix(mid.strip())
        if pref:
            return normalize_provider_slug(pref)
    return None


# Typical vendor guidance; APIs still enforce their own bounds.
_SAMPLING_GUIDES: dict[str, dict[str, dict[str, Any]]] = {
    "generic": {
        "temperature": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 2.0,
            "notes": "Many chat APIs use 0–2; some providers cap lower (e.g. Anthropic 0–1).",
        },
        "top_p": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 1.0,
            "notes": "Nucleus sampling; 1.0 disables top-p filtering on most APIs.",
        },
        "top_k": {
            "recommended_default": None,
            "typical_min": None,
            "typical_max": None,
            "notes": "Supported on some providers (Anthropic, Gemini, Groq); omit when unsupported.",
        },
    },
    "openai": {
        "temperature": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 2.0,
            "notes": "OpenAI Chat Completions: 0–2 default 1.",
        },
        "top_p": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 1.0,
            "notes": "OpenAI nucleus sampling.",
        },
        "frequency_penalty": {
            "recommended_default": 0.0,
            "typical_min": -2.0,
            "typical_max": 2.0,
            "notes": "Penalize tokens by frequency.",
        },
        "presence_penalty": {
            "recommended_default": 0.0,
            "typical_min": -2.0,
            "typical_max": 2.0,
            "notes": "Penalize tokens by presence.",
        },
    },
    "anthropic": {
        "temperature": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 1.0,
            "notes": "Anthropic Messages API commonly documents 0–1.",
        },
        "top_p": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 1.0,
            "notes": "Nucleus sampling; LangChain may accept sentinel values to disable.",
        },
        "top_k": {
            "recommended_default": None,
            "typical_min": -1,
            "typical_max": None,
            "notes": "Optional top_k where supported.",
        },
    },
    "google": {
        "temperature": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 2.0,
            "notes": "Gemini generation config.",
        },
        "top_p": {
            "recommended_default": 0.95,
            "typical_min": 0.0,
            "typical_max": 1.0,
            "notes": "Gemini top_p.",
        },
        "top_k": {
            "recommended_default": None,
            "typical_min": 1,
            "typical_max": None,
            "notes": "Candidate sampling top_k.",
        },
    },
    "groq": {
        "temperature": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 2.0,
            "notes": "Groq OpenAI-compatible chat.",
        },
        "top_p": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 1.0,
            "notes": "Nucleus sampling.",
        },
    },
    "mistralai": {
        "temperature": {
            "recommended_default": 0.7,
            "typical_min": 0.0,
            "typical_max": 1.5,
            "notes": "Mistral chat typical ranges.",
        },
        "top_p": {
            "recommended_default": 1.0,
            "typical_min": 0.0,
            "typical_max": 1.0,
            "notes": "Nucleus sampling.",
        },
    },
}


def _guide_for_slug(slug: str | None) -> dict[str, dict[str, Any]]:
    base = dict(_SAMPLING_GUIDES["generic"])
    if slug and slug in _SAMPLING_GUIDES:
        base.update(_SAMPLING_GUIDES[slug])
    return base


def recommended_defaults_table(slug: str | None) -> dict[str, float | None]:
    """Flat recommended defaults only (JSON-serializable)."""
    g = _guide_for_slug(slug)
    out: dict[str, float | None] = {}
    for name, meta in g.items():
        rd = meta.get("recommended_default")
        if rd is None:
            continue
        out[name] = float(rd) if isinstance(rd, (int, float)) else None
    return out


def build_sampling_section_for_session_marker(args: Namespace) -> dict[str, Any]:
    """Snapshot for ``.agloom/sessions/*.json``: effective argv + provider guides."""
    slug = infer_provider_slug_from_args(args)
    guides = _guide_for_slug(slug)
    effective: dict[str, Any] = {}
    t = getattr(args, "temperature", None)
    if t is not None:
        effective["temperature"] = float(t)
    tp = getattr(args, "top_p", None)
    if tp is not None:
        effective["top_p"] = float(tp)
    tk = getattr(args, "top_k", None)
    if tk is not None:
        effective["top_k"] = int(tk)

    return {
        "provider_slug": slug or "unknown",
        "effective": effective,
        "recommended_defaults": recommended_defaults_table(slug),
        "parameters": guides,
    }
