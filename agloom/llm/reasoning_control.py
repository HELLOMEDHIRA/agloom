"""Provider-agnostic reasoning ON/OFF control and reasoning-active detection.

agloom is provider-neutral: reasoning behavior must never be hardcoded to one vendor.
This module maps a single boolean preference (``enable``) to the correct provider knob
and detects whether a model is running in a reasoning/thinking mode so timeouts can scale.

Knob map (by resolved provider family):
    vLLM / LiteLLM / strict-template (Qwen/QwQ) -> extra_body.chat_template_kwargs.enable_thinking
    Anthropic (incl. Bedrock/Vertex Anthropic)  -> thinking = {"type": "enabled"|"disabled"}
    Google / Gemini / Vertex                     -> thinking_budget (0 disables, -1 dynamic)
    Groq                                         -> reasoning_effort ("none" disables)
    OpenAI o-series (no runtime toggle)          -> no-op (rely on parser + timeout scaling)
    enable=None                                  -> inject nothing (respect model/gateway)
"""

from __future__ import annotations

import re
from typing import Any

# Model-id / label markers that indicate a reasoning-first model family (any provider).
_REASONING_MODEL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bo[1345](?:-|\b)"),  # OpenAI o1/o3/o4/o5-series
    re.compile(r"deepseek[-_]?r\d"),  # deepseek-r1, deepseek_r1
    re.compile(r"\bqwq\b"),  # Qwen QwQ reasoning line
    re.compile(r"qwen[\w.-]*thinking"),  # qwen*-thinking
    re.compile(r"gemini[\w.-]*thinking"),  # gemini-*-thinking
    re.compile(r"claude[\w.-]*thinking"),  # claude-*-thinking
    re.compile(r"magistral"),  # Mistral reasoning line
    re.compile(r"grok[\w.-]*(?:reason|think)"),
)

# Strict / OpenAI-compatible chat-template families that accept ``chat_template_kwargs``.
_STRICT_LABEL_MARKERS = ("vllm", "litellm", "qwen", "qwq", "chatlitellm")


def _label(model_label: str | None) -> str:
    return (model_label or "").lower()


def label_indicates_reasoning_model(model_label: str | None) -> bool:
    """True when the model id/label matches a known reasoning model family."""
    low = _label(model_label)
    if not low:
        return False
    return any(p.search(low) for p in _REASONING_MODEL_PATTERNS)


def _reasoning_family(model_label: str | None) -> str:
    """Resolve the provider family that governs the reasoning knob."""
    low = _label(model_label)
    # Anthropic / Google / Groq take priority over generic OpenAI-compat detection so a
    # native ``claude``/``gemini``/``groq`` label maps to its dedicated knob.
    if "claude" in low or "anthropic" in low:
        return "anthropic"
    if "gemini" in low or "google" in low or "vertex" in low:
        return "google"
    if "groq" in low:
        return "groq"
    if any(m in low for m in _STRICT_LABEL_MARKERS):
        return "strict"
    return "generic"


def reasoning_preference_kwargs(*, enable: bool | None, model_label: str | None) -> dict[str, Any]:
    """Return the provider-correct model-settings/bind kwargs for a reasoning preference.

    ``enable=None`` returns ``{}`` (inject nothing). Providers without a runtime toggle
    (e.g. OpenAI o-series) also return ``{}`` — the inline parser and timeout scaling keep
    those correct.
    """
    if enable is None:
        return {}
    family = _reasoning_family(model_label)
    if family == "strict":
        return {"extra_body": {"chat_template_kwargs": {"enable_thinking": enable}}}
    if family == "anthropic":
        if enable:
            return {"thinking": {"type": "enabled", "budget_tokens": 2048}}
        return {"thinking": {"type": "disabled"}}
    if family == "google":
        # 0 disables; -1 requests dynamic/auto thinking budget.
        return {"thinking_budget": -1 if enable else 0}
    if family == "groq":
        return {"reasoning_effort": "default" if enable else "none"}
    return {}


def _deep_merge_settings(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Merge reasoning kwargs into a model_settings dict (nested dicts merged, not clobbered)."""
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_settings(out[key], value)
        else:
            out[key] = value
    return out


def apply_reasoning_preference(
    target: Any,
    *,
    enable: bool | None,
    model_label: str | None,
) -> Any:
    """Apply a reasoning preference to a model_settings dict or an LLM instance.

    - dict target (middleware ``model_settings``): returns a merged copy.
    - LLM target: returns ``target.bind(**kwargs)`` (a new runnable) or ``target`` when no-op.
    """
    kwargs = reasoning_preference_kwargs(enable=enable, model_label=model_label)
    if isinstance(target, dict):
        if not kwargs:
            return dict(target)
        return _deep_merge_settings(target, kwargs)
    if not kwargs:
        return target
    bind = getattr(target, "bind", None)
    if callable(bind):
        try:
            return bind(**kwargs)
        except Exception:
            return target
    return target


def _extra_body_enable_thinking(container: Any) -> bool | None:
    if not isinstance(container, dict):
        return None
    ctk = container.get("chat_template_kwargs")
    if isinstance(ctk, dict) and "enable_thinking" in ctk:
        val = ctk.get("enable_thinking")
        if isinstance(val, bool):
            return val
    return None


def _llm_has_active_reasoning_param(llm: Any) -> bool:
    """True when an LLM instance already carries a truthy reasoning parameter."""
    if llm is None:
        return False

    thinking = getattr(llm, "thinking", None)
    if isinstance(thinking, dict):
        if str(thinking.get("type", "")).lower() == "enabled":
            return True
    elif thinking:
        return True

    budget = getattr(llm, "thinking_budget", None)
    if isinstance(budget, int) and budget != 0:
        return True

    effort = getattr(llm, "reasoning_effort", None)
    if isinstance(effort, str) and effort.strip().lower() not in ("", "none"):
        return True

    for attr in ("reasoning_format", "reasoning", "include_reasoning"):
        val = getattr(llm, attr, None)
        if isinstance(val, bool):
            if val:
                return True
        elif val:
            return True

    for attr in ("extra_body", "model_kwargs"):
        container = getattr(llm, attr, None)
        if isinstance(container, dict):
            direct = _extra_body_enable_thinking(container.get("extra_body") or container)
            if direct is True:
                return True
    return False


# Library default timeouts (must match create_agent signature defaults) and the raised
# floors applied when a reasoning-active model is detected.
_DEFAULT_LLM_TIMEOUT = 120.0
_DEFAULT_CLASSIFIER_TIMEOUT = 60.0
_REASONING_LLM_TIMEOUT_FLOOR = 300.0
_REASONING_CLASSIFIER_TIMEOUT_FLOOR = 120.0


def scaled_timeouts_for_reasoning(
    llm_timeout: float,
    classifier_timeout: float,
) -> tuple[float, float]:
    """Raise default timeout floors for reasoning-active models, preserving explicit overrides.

    Only the library defaults (120s llm / 60s classifier) are bumped; any other value is treated
    as an explicit ``create_agent`` override and left unchanged. Callers should invoke this only
    when :func:`reasoning_is_active` returns ``True``.
    """
    if llm_timeout == _DEFAULT_LLM_TIMEOUT:
        llm_timeout = _REASONING_LLM_TIMEOUT_FLOOR
    if classifier_timeout == _DEFAULT_CLASSIFIER_TIMEOUT:
        classifier_timeout = _REASONING_CLASSIFIER_TIMEOUT_FLOOR
    return llm_timeout, classifier_timeout


def reasoning_is_active(
    llm: Any = None,
    *,
    enable_thinking: bool | None = None,
    model_label: str | None = None,
) -> bool:
    """Vendor-neutral detection of whether reasoning/thinking is active for this model.

    True when the agent explicitly enabled thinking, OR the LLM already carries a truthy
    reasoning parameter, OR the model id/label matches a known reasoning model family.
    ``enable_thinking=False`` does not by itself force ``False`` — a reasoning-model family
    may still monologue — but an explicit ``True`` always counts as active.
    """
    if enable_thinking is True:
        return True
    if _llm_has_active_reasoning_param(llm):
        return True
    return label_indicates_reasoning_model(model_label)
