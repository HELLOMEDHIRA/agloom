"""Model resolution — auto-detect available LLM providers for the CLI.

LangChain publishes many chat integrations; the canonical doc index is
https://docs.langchain.com/oss/python/integrations/chat

``pyproject.toml`` defines optional extras ``agloom[<name>]`` for each first-party
``langchain-*`` integration package (plus ``community`` for long-tail models). Combine extras
as needed (e.g. ``pip install 'agloom[openai,groq]'``).
Only a **small subset** is wired in this module for ``agloom`` CLI env-based defaults.
Other backends: ``pip install 'agloom[aws]'`` / ``'agloom[litellm]'`` / … (or plain
``langchain-*``), then ``init_chat_model`` or pass ``BaseChatModel``
(``agloom.unified_agent.resolve_model``).
"""

from __future__ import annotations

import os
from typing import Any


def _env_configured(names: str | tuple[str, ...]) -> bool:
    if isinstance(names, str):
        return bool(os.environ.get(names))
    return any(os.environ.get(n) for n in names)


def _google_api_key() -> str | None:
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")


def _looks_like_mistral_ai_cloud(model_id: str) -> bool:
    """Native Mistral AI API model ids (not Groq-hosted ``open-mixtral`` / etc.)."""
    m = model_id.lower()
    if m.startswith(("mistral-", "ministral")):
        return True
    return any(p in m for p in ("pixtral", "codestral"))


class MissingProviderDependency(ImportError):
    """Optional LangChain provider package is not installed (``agloom[extra]``)."""

    def __init__(self, extra: str, pip_hint: str, *, detail: str | None = None) -> None:
        self.extra = extra
        self.pip_hint = pip_hint
        if detail is not None:
            super().__init__(detail)
        else:
            super().__init__(
                f"Missing optional LLM integration (install extra '{extra}'). "
                f"Example: pip install {pip_hint}"
            )


def get_model(model_id: str, **kwargs) -> Any:
    """Get a LangChain chat model by ID (CLI-curated routing only).

    Dozens of other backends exist under separate PyPI packages; see the module docstring URL.
    For those, install the integration from LangChain's docs and use ``init_chat_model`` or a
    concrete ``BaseChatModel`` in application code — not this helper.

    Optional extras match ``[project.optional-dependencies]`` in ``pyproject.toml``
    (e.g. ``openai``, ``aws``, ``litellm``, ``community``).

    - OpenAI: gpt-4o, gpt-4o-mini, …
    - Anthropic: claude-…
    - Google Gemini: gemini-… (``GOOGLE_API_KEY`` or ``GEMINI_API_KEY``)
    - xAI: grok-… (``XAI_API_KEY``)
    - Mistral AI: mistral-…, ministral…, pixtral…, codestral… (``MISTRAL_API_KEY``)
    - Groq: meta-llama/…, …
    - Ollama: local names when ``OLLAMA_HOST`` is set

    Args:
        model_id: Model identifier
        **kwargs: Additional model parameters (temperature, etc.)

    Returns:
        LangChain BaseChatModel instance
    """
    model_id_lower = model_id.lower()

    if model_id_lower.startswith(("gpt-", "o1")):
        return _get_openai_model(model_id, **kwargs)

    if "claude" in model_id_lower or model_id_lower.startswith("anthropic"):
        return _get_anthropic_model(model_id, **kwargs)

    if "gemini" in model_id_lower or model_id_lower.startswith("models/gemini"):
        return _get_google_genai_model(model_id, **kwargs)

    if "grok" in model_id_lower:
        return _get_xai_model(model_id, **kwargs)

    if "groq" in model_id_lower:
        return _get_groq_model(model_id, **kwargs)

    if "/" in model_id and not model_id_lower.startswith(("openai/", "anthropic/")):
        return _get_groq_model(model_id, **kwargs)

    if _looks_like_mistral_ai_cloud(model_id):
        return _get_mistral_model(model_id, **kwargs)

    if "llama" in model_id_lower or "mistral" in model_id_lower:
        if os.environ.get("OLLAMA_HOST"):
            return _get_ollama_model(model_id, **kwargs)
        return _get_groq_model(model_id, **kwargs)

    return _get_default_model(model_id, **kwargs)


def try_resolve_llm_from_api_keys() -> Any | None:
    """Pick the first usable default model from API keys in priority order.

    Skips providers whose optional packages are not installed (so e.g. a stray
    ``OPENAI_API_KEY`` does not block ``GROQ_API_KEY`` when only ``agloom[groq]`` is installed).
    """
    candidates: list[tuple[str | tuple[str, ...], str]] = [
        ("OPENAI_API_KEY", "gpt-4o"),
        ("ANTHROPIC_API_KEY", "claude-3-5-sonnet-20241022"),
        (("GOOGLE_API_KEY", "GEMINI_API_KEY"), "gemini-2.0-flash"),
        ("MISTRAL_API_KEY", "mistral-large-latest"),
        ("GROQ_API_KEY", "meta-llama/llama-4-scout-17b-16e-instruct"),
        ("XAI_API_KEY", "grok-3-latest"),
    ]
    # Skip MissingProviderDependency instead of surfacing the *first* failing provider:
    # e.g. OPENAI_API_KEY may be set globally while only ``agloom[groq]`` is installed —
    # later candidates (GROQ_API_KEY, …) must still be tried.
    missing_for_configured_keys: list[MissingProviderDependency] = []
    for env_spec, default_model in candidates:
        if not _env_configured(env_spec):
            continue
        try:
            return get_model(default_model)
        except MissingProviderDependency as e:
            missing_for_configured_keys.append(e)
            continue
    if missing_for_configured_keys:
        by_extra: dict[str, MissingProviderDependency] = {}
        for e in missing_for_configured_keys:
            by_extra[e.extra] = e
        if len(by_extra) == 1:
            e = next(iter(by_extra.values()))
            raise e
        parts = " ".join(
            f"For extra '{e.extra}': pip install {e.pip_hint}." for e in by_extra.values()
        )
        raise MissingProviderDependency(
            "multiple",
            "'agloom[<provider>]'",
            detail=(
                "API keys are set but the matching LangChain integrations are not installed. "
                + parts
                + " Or unset unused API_KEY variables so another provider can be used."
            ),
        )
    return None


def _get_openai_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise MissingProviderDependency("openai", "'agloom[openai]'") from e

    return ChatOpenAI(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=os.environ.get("OPENAI_API_KEY"),
    )


def _get_anthropic_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        raise MissingProviderDependency("anthropic", "'agloom[anthropic]'") from e

    actual_model = model_id
    if "claude-3" in model_id.lower():
        if "sonnet" in model_id.lower():
            actual_model = "claude-3-5-sonnet-20241022"
        elif "opus" in model_id.lower():
            actual_model = "claude-3-opus-20240229"
        elif "haiku" in model_id.lower():
            actual_model = "claude-3-haiku-20240307"

    return ChatAnthropic(
        model=actual_model,
        temperature=kwargs.get("temperature", 0),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )


def _get_google_genai_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise MissingProviderDependency("google-genai", "'agloom[google-genai]'") from e

    key = _google_api_key()
    return ChatGoogleGenerativeAI(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=key,
    )


def _get_mistral_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_mistralai import ChatMistralAI
    except ImportError as e:
        raise MissingProviderDependency("mistralai", "'agloom[mistralai]'") from e

    return ChatMistralAI(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=os.environ.get("MISTRAL_API_KEY"),
    )


def _get_xai_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_xai import ChatXAI
    except ImportError as e:
        raise MissingProviderDependency("xai", "'agloom[xai]'") from e

    return ChatXAI(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=os.environ.get("XAI_API_KEY"),
    )


def _get_groq_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_groq import ChatGroq
    except ImportError as e:
        raise MissingProviderDependency("groq", "'agloom[groq]'") from e

    return ChatGroq(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=os.environ.get("GROQ_API_KEY"),
    )


def _get_ollama_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise MissingProviderDependency("ollama", "'agloom[ollama]'") from e

    return ChatOllama(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
    )


def _get_default_model(model_id: str, **kwargs) -> Any:
    if os.environ.get("OPENAI_API_KEY"):
        return _get_openai_model("gpt-4o", **kwargs)

    if os.environ.get("ANTHROPIC_API_KEY"):
        return _get_anthropic_model("claude-3-5-sonnet-20241022", **kwargs)

    if _google_api_key():
        return _get_google_genai_model("gemini-2.0-flash", **kwargs)

    if os.environ.get("MISTRAL_API_KEY"):
        return _get_mistral_model("mistral-large-latest", **kwargs)

    if os.environ.get("GROQ_API_KEY"):
        return _get_groq_model("meta-llama/llama-4-scout-17b-16e-instruct", **kwargs)

    if os.environ.get("XAI_API_KEY"):
        return _get_xai_model("grok-3-latest", **kwargs)

    raise ValueError(
        "No model found. Set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY or GEMINI_API_KEY, "
        "MISTRAL_API_KEY, GROQ_API_KEY, XAI_API_KEY"
    )
