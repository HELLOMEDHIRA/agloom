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
import sys
from importlib import util
from typing import Any

# CLI auto-pick order: (slug for ``AGLOOM_PROVIDER``, Rich label, env var(s), default model id).
_CLI_PROVIDER_ROWS: list[tuple[str, str, str | tuple[str, ...], str]] = [
    ("openai", "OpenAI", "OPENAI_API_KEY", "gpt-4o"),
    ("anthropic", "Anthropic", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-20241022"),
    ("google", "Google Gemini", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), "gemini-2.0-flash"),
    ("mistralai", "Mistral AI", "MISTRAL_API_KEY", "mistral-large-latest"),
    ("groq", "Groq", "GROQ_API_KEY", "meta-llama/llama-4-scout-17b-16e-instruct"),
    ("xai", "xAI", "XAI_API_KEY", "grok-3-latest"),
]

_SLUG_TO_EXTRA: dict[str, tuple[str, str]] = {
    "openai": ("openai", "'agloom[openai]'"),
    "anthropic": ("anthropic", "'agloom[anthropic]'"),
    "google": ("google-genai", "'agloom[google-genai]'"),
    "mistralai": ("mistralai", "'agloom[mistralai]'"),
    "groq": ("groq", "'agloom[groq]'"),
    "xai": ("xai", "'agloom[xai]'"),
}

_SLUG_TO_IMPORT: dict[str, str] = {
    "openai": "langchain_openai",
    "anthropic": "langchain_anthropic",
    "google": "langchain_google_genai",
    "mistralai": "langchain_mistralai",
    "groq": "langchain_groq",
    "xai": "langchain_xai",
}


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


class MissingProviderApiKey(ValueError):
    """Required API key for the resolved provider is not set (avoid SDK tracebacks)."""


def _require_env(name: str, *, for_provider: str) -> str:
    v = os.environ.get(name)
    if v:
        return v
    raise MissingProviderApiKey(
        f"{name} is not set. Export it to use {for_provider} models "
        f"(e.g. `set {name}=...` on Windows or `export {name}=...` in bash)."
    )


def _require_google_api_key() -> str:
    k = _google_api_key()
    if k:
        return k
    raise MissingProviderApiKey(
        "GOOGLE_API_KEY or GEMINI_API_KEY must be set for Gemini models."
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


def _integration_importable(slug: str) -> bool:
    mod = _SLUG_TO_IMPORT.get(slug)
    if not mod:
        return False
    return util.find_spec(mod) is not None


def _usable_cli_provider_triples() -> tuple[list[tuple[str, str, str]], list[MissingProviderDependency]]:
    """Providers with env key(s) set **and** integration importable → one ``get_model`` call each later."""
    usable: list[tuple[str, str, str]] = []
    missing: list[MissingProviderDependency] = []
    for slug, label, env_spec, default_model in _CLI_PROVIDER_ROWS:
        if not _env_configured(env_spec):
            continue
        if not _integration_importable(slug):
            ex, hint = _SLUG_TO_EXTRA[slug]
            missing.append(MissingProviderDependency(ex, hint))
            continue
        usable.append((slug, label, default_model))
    return usable, missing


def try_resolve_llm_from_api_keys(*, interactive: bool | None = None) -> Any | None:
    """Pick a default model from API keys.

    - If exactly one provider is usable (key set + extra installed), use it.
    - If several are usable and stdin/stdout are TTYs, prompt for a choice (override with ``AGLOOM_PROVIDER``).
    - If several are usable but not interactive, use the first in priority order (same as before).

    Skips providers whose optional packages are not installed.
    """
    usable, missing_for_configured_keys = _usable_cli_provider_triples()
    if not usable:
        if missing_for_configured_keys:
            by_extra: dict[str, MissingProviderDependency] = {}
            for e in missing_for_configured_keys:
                by_extra[e.extra] = e
            if len(by_extra) == 1:
                raise next(iter(by_extra.values()))
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

    pref = (os.environ.get("AGLOOM_PROVIDER") or "").strip().lower()
    if pref:
        for slug, _label, default_model in usable:
            if slug == pref:
                return get_model(default_model)

    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if len(usable) == 1:
        return get_model(usable[0][2])

    if interactive and len(usable) > 1:
        from rich.console import Console
        from rich.prompt import IntPrompt

        slug_hint = ", ".join(s for s, _, __ in usable)
        Console().print(
            f"\n[bold cyan]Multiple LLM API keys detected. Choose provider:[/bold cyan] "
            f"[dim](or set AGLOOM_PROVIDER to one of: {slug_hint})[/dim]\n",
        )
        for i, (slug, label, default_model) in enumerate(usable, start=1):
            Console().print(
                f"  {i}. [green]{label}[/green] [dim]({slug})[/dim] — default model [cyan]{default_model}[/cyan]"
            )
        choice = IntPrompt.ask("Enter number", default=1)
        idx = max(1, min(choice, len(usable))) - 1
        return get_model(usable[idx][2])

    return get_model(usable[0][2])


def describe_llm(llm: Any) -> tuple[str, str]:
    """Return ``(provider_slug, model_id)`` for status lines (e.g. REPL INFO panel)."""
    cls_name = type(llm).__name__.lower()
    mid = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    mid_s = str(mid).strip() if mid else "auto"

    if "groq" in cls_name:
        return "groq", mid_s
    if "openai" in cls_name or cls_name == "chatopenai":
        return "openai", mid_s
    if "anthropic" in cls_name or "claude" in cls_name:
        return "anthropic", mid_s
    if "google" in cls_name or "gemini" in cls_name:
        return "google", mid_s
    if "mistral" in cls_name:
        return "mistralai", mid_s
    if "xai" in cls_name or "grok" in cls_name:
        return "xai", mid_s
    if "ollama" in cls_name:
        return "ollama", mid_s
    return type(llm).__name__.replace("Chat", "").lower() or "llm", mid_s


def _get_openai_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise MissingProviderDependency("openai", "'agloom[openai]'") from e

    return ChatOpenAI(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=_require_env("OPENAI_API_KEY", for_provider="OpenAI"),
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
        anthropic_api_key=_require_env("ANTHROPIC_API_KEY", for_provider="Anthropic"),
    )


def _get_google_genai_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise MissingProviderDependency("google-genai", "'agloom[google-genai]'") from e

    key = _require_google_api_key()
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
        api_key=_require_env("MISTRAL_API_KEY", for_provider="Mistral AI"),
    )


def _get_xai_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_xai import ChatXAI
    except ImportError as e:
        raise MissingProviderDependency("xai", "'agloom[xai]'") from e

    return ChatXAI(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=_require_env("XAI_API_KEY", for_provider="xAI"),
    )


def _get_groq_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_groq import ChatGroq
    except ImportError as e:
        raise MissingProviderDependency("groq", "'agloom[groq]'") from e

    return ChatGroq(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=_require_env("GROQ_API_KEY", for_provider="Groq"),
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
