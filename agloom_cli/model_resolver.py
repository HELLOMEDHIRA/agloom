"""Model resolution — auto-detect available LLM providers for the CLI.

LangChain publishes many chat integrations; the canonical doc index is
https://docs.langchain.com/oss/python/integrations/chat  
Full provider list: https://docs.langchain.com/oss/python/integrations/providers/all_providers

**Explicit provider** (recommended for ``org/model`` ids such as ``meta-llama/...``):

- ``agloom -m groq:meta-llama/llama-4-scout-17b-16e-instruct``
- ``agloom -m ollama:llama3.2 --base-url http://192.168.1.10:11434``
- Config: ``ai.provider: groq`` with ``ai.model: meta-llama/...``, optional ``ai.base_url``.

**Broad routing** (install the matching optional extra from ``pyproject.toml``):

- **LiteLLM** (100+ upstream providers via one adapter): ``agloom -m litellm:groq/llama-3.3-70b-versatile``
  or ``ai.provider: litellm`` + ``ai.model: …``. Optional ``--base-url`` maps to LiteLLM ``api_base``.
- **Any LangChain integration** via the unified initializer: ``agloom -m lc:openai:gpt-4o`` or
  ``agloom -m init:groq:meta-llama/...`` (same as ``langchain.chat_models.init_chat_model``). Requires
  the provider’s ``langchain-*`` package (e.g. ``agloom[openai]``, ``agloom[groq]``).
- **OpenRouter**: ``agloom -m openrouter:anthropic/claude-3.5-sonnet`` (needs ``agloom[openrouter]``).

``vLLM`` uses OpenAI-compatible HTTP (see LangChain `ChatOpenAI` + ``base_url``):
https://docs.langchain.com/oss/python/integrations/chat/vllm

``pyproject.toml`` defines optional extras ``agloom[<name>]`` for each first-party
``langchain-*`` integration package (plus ``community`` for long-tail models). Combine extras
as needed (e.g. ``pip install 'agloom[openai,groq,ollama,litellm]'``).
Curated first-party slugs (OpenAI, Groq, …) keep strict API-key checks. **Any other**
``provider:model`` token (e.g. ``cohere:command-r``, ``bedrock:…``, ``google_vertexai:…``)
routes to ``langchain.chat_models.init_chat_model`` — the same provider list as
https://docs.langchain.com/oss/python/integrations/providers/all_providers (install the matching
``langchain-*`` extra or ``agloom[community]`` for long-tail integrations). Use ``litellm:…`` for
LiteLLM’s unified router, or ``lc:`` / ``init:`` to pass a full prefixed descriptor.
"""

from __future__ import annotations

import os
import re
import sys
from importlib import util
from typing import Any

from agloom_cli.llm_provider_params import normalize_provider_slug, spread_llm_options_for_provider


def _slug_for_spread_llm(*, model_provider: str | None, model: str) -> str:
    """Provider slug for :func:`spread_llm_options_for_provider` when using ``init_chat_model``."""
    if model_provider:
        return normalize_provider_slug(model_provider)
    pref, _rest = split_provider_prefix(model)
    if pref and pref not in ("lc", "init"):
        return normalize_provider_slug(pref)
    return "__generic_init__"

# CLI auto-pick order: (slug for ``AGLOOM_PROVIDER``, Rich label, env var(s), default model id).
_CLI_PROVIDER_ROWS: list[tuple[str, str, str | tuple[str, ...], str]] = [
    ("openai", "OpenAI", "OPENAI_API_KEY", "gpt-4o"),
    ("anthropic", "Anthropic", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-20241022"),
    ("google", "Google Gemini", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), "gemini-2.0-flash"),
    ("mistralai", "Mistral AI", "MISTRAL_API_KEY", "mistral-large-latest"),
    ("groq", "Groq", "GROQ_API_KEY", "meta-llama/llama-4-scout-17b-16e-instruct"),
    ("xai", "xAI", "XAI_API_KEY", "grok-3-latest"),
]

# Env vars to snapshot into ``ai.api_keys`` when saving session YAML (wizard / augment_patch).
_PROVIDER_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "mistralai": ("MISTRAL_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "ollama": (),
    "vllm": ("OPENAI_API_KEY", "VLLM_API_KEY"),
    "litellm": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "cerebras": ("CEREBRAS_API_KEY",),
    "nvidia": ("NVIDIA_API_KEY",),
    "cohere": ("COHERE_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "fireworks": ("FIREWORKS_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
    "perplexity": ("PERPLEXITY_API_KEY",),
    "upstage": ("UPSTAGE_API_KEY",),
    "ibm": ("WATSONX_API_KEY",),
    "huggingface": ("HUGGINGFACEHUB_API_TOKEN",),
    "baseten": ("BASETEN_API_KEY",),
    "azure_openai": ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"),
    "azure_ai": ("AZURE_AI_API_KEY", "AZURE_AI_ENDPOINT"),
}


def augment_patch_api_keys_from_env(patch: dict[str, Any]) -> dict[str, Any]:
    """Add ``api_keys`` from :func:`os.environ` for the resolved provider without clobbering *patch*.

    Wizard-entered keys win; we only ``setdefault`` env values so a session YAML can carry the same
    secrets the user already exported (portable session files).
    """
    model = str(patch.get("model") or "").strip()
    prov_hint = patch.get("provider")
    if isinstance(prov_hint, str):
        prov_hint = prov_hint.strip() or None
    pref, _rest = split_provider_prefix(model)
    raw_tok = (pref or prov_hint or "").strip().lower().replace("-", "_")
    if raw_tok in ("mistral",):
        raw_tok = "mistralai"
    if raw_tok in ("google", "gemini"):
        raw_tok = "google"
    keys_tpl = _PROVIDER_ENV_KEYS.get(raw_tok, ())
    snap: dict[str, str] = {}
    for name in keys_tpl:
        v = os.environ.get(name)
        if v and str(v).strip():
            snap[name] = str(v).strip()
    if not snap:
        return patch
    merged = dict(patch.get("api_keys") or {})
    for k, v in snap.items():
        merged.setdefault(k, v)
    out = dict(patch)
    out["api_keys"] = merged
    return out

_SLUG_TO_EXTRA: dict[str, tuple[str, str]] = {
    "openai": ("openai", "'agloom[openai]'"),
    "anthropic": ("anthropic", "'agloom[anthropic]'"),
    "google": ("google-genai", "'agloom[google-genai]'"),
    "mistralai": ("mistralai", "'agloom[mistralai]'"),
    "groq": ("groq", "'agloom[groq]'"),
    "xai": ("xai", "'agloom[xai]'"),
    "ollama": ("ollama", "'agloom[ollama]'"),
    "vllm": ("openai", "'agloom[openai]'"),
    "litellm": ("litellm", "'agloom[litellm]'"),
    "openrouter": ("openrouter", "'agloom[openrouter]'"),
    "cerebras": ("cerebras", "'agloom[cerebras]'"),
}

_SLUG_TO_IMPORT: dict[str, str] = {
    "openai": "langchain_openai",
    "anthropic": "langchain_anthropic",
    "google": "langchain_google_genai",
    "mistralai": "langchain_mistralai",
    "groq": "langchain_groq",
    "xai": "langchain_xai",
    "ollama": "langchain_ollama",
    "litellm": "langchain_litellm",
    "openrouter": "langchain_openrouter",
    "cerebras": "langchain_cerebras",
}

# URI schemes: first ``:`` is not ``provider:model`` (avoids ``https://...`` false splits).
_URI_SCHEME_PREFIXES: frozenset[str] = frozenset({"http", "https", "file", "urn", "data", "ftp"})
# Provider token for ``slug:model_id`` (matches LangChain ``model_provider`` / LiteLLM-style slugs).
_PROVIDER_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def split_provider_prefix(spec: str) -> tuple[str | None, str]:
    """Split ``provider:model_id`` for any LangChain ``model_provider``-style *provider*.

    - ``lc:`` / ``init:`` use only the first colon; the rest may contain ``:`` (full ``init_chat_model`` descriptor).
    - Otherwise, the left segment must match ``_PROVIDER_TOKEN_RE`` (e.g. ``cohere:command-r``, ``bedrock:...``).
    - URIs (``https://``, …) are not split.
    """
    spec = spec.strip()
    if ":" not in spec:
        return None, spec
    left, _, right = spec.partition(":")
    key = left.strip()
    rest = right.strip()
    if not key or not rest:
        return None, spec
    kl = key.lower()
    if kl in ("lc", "init"):
        return kl, rest
    if kl in _URI_SCHEME_PREFIXES:
        return None, spec
    if not _PROVIDER_TOKEN_RE.fullmatch(kl):
        return None, spec
    return kl.replace("-", "_"), rest


def provider_slug_token_valid(slug: str) -> bool:
    """True if *slug* is usable as ``AGLOOM_PROVIDER`` / ``ai.provider`` (alphanumeric token)."""
    s = slug.strip().lower().replace("-", "_")
    return bool(_PROVIDER_TOKEN_RE.fullmatch(s))


def _default_ollama_base_url(explicit: str | None) -> str | None:
    if explicit:
        return explicit.strip()
    return os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")


def _default_vllm_base_url(explicit: str | None) -> str:
    base = (explicit or os.environ.get("VLLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "").strip()
    if not base:
        return "http://127.0.0.1:8000/v1"
    base = base.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


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
        f"(e.g. `set {name}=...` on Windows or `export {name}=...` in bash), "
        f"or add it under `ai.api_keys` in agloom.yaml (local / project-level config)."
    )


def _require_google_api_key() -> str:
    k = _google_api_key()
    if k:
        return k
    raise MissingProviderApiKey(
        "GOOGLE_API_KEY or GEMINI_API_KEY must be set for Gemini models "
        "(environment or `ai.api_keys` in agloom.yaml)."
    )


def _init_chat_model_unified(
    model: str,
    *,
    model_provider: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> Any:
    """``langchain.chat_models.init_chat_model`` — supports ``provider:model_id`` strings."""
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as e:
        raise MissingProviderDependency(
            "langchain",
            "'agloom' (core langchain dependency)",
        ) from e

    filt = _slug_for_spread_llm(model_provider=model_provider, model=model)
    init_kw: dict[str, Any] = spread_llm_options_for_provider(filt, kwargs)
    init_kw.setdefault("temperature", 0)
    if base_url:
        init_kw["base_url"] = base_url.strip()
    if model_provider:
        return init_chat_model(model, model_provider=model_provider, **init_kw)
    return init_chat_model(model, **init_kw)


def _get_litellm_model(model_id: str, *, base_url: str | None = None, **kwargs: Any) -> Any:
    """LiteLLM-backed chat model (routes to many upstream APIs)."""
    try:
        from langchain_litellm import ChatLiteLLM
    except ImportError as e:
        raise MissingProviderDependency("litellm", "'agloom[litellm]'") from e

    params: dict[str, Any] = {
        "model": model_id,
        **spread_llm_options_for_provider("litellm", kwargs),
    }
    if "temperature" not in params:
        params["temperature"] = kwargs.get("temperature", 0)
    if base_url:
        params["api_base"] = base_url.strip()
    return ChatLiteLLM(**params)


def _get_by_provider(
    slug: str,
    model_id: str,
    *,
    base_url: str | None = None,
    **kwargs: Any,
) -> Any:
    """Construct a chat model from an explicit provider slug (curated + ``init_chat_model``)."""
    s = slug.strip().lower().replace("-", "_")
    if s in ("mistral",):
        s = "mistralai"
    if s in ("google", "gemini"):
        return _get_google_genai_model(model_id, **kwargs)
    if s == "openai":
        return _get_openai_model(model_id, base_url=base_url, **kwargs)
    if s == "anthropic":
        return _get_anthropic_model(model_id, **kwargs)
    if s == "mistralai":
        return _get_mistral_model(model_id, **kwargs)
    if s == "xai":
        return _get_xai_model(model_id, **kwargs)
    if s == "groq":
        return _get_groq_model(model_id, **kwargs)
    if s == "ollama":
        return _get_ollama_model(model_id, base_url=_default_ollama_base_url(base_url), **kwargs)
    if s == "vllm":
        return _get_vllm_openai_compatible(model_id, base_url=base_url, **kwargs)
    if s == "litellm":
        return _get_litellm_model(model_id, base_url=base_url, **kwargs)
    if s in ("lc", "init"):
        return _init_chat_model_unified(model_id, base_url=base_url, **kwargs)
    if s == "openrouter":
        return _init_chat_model_unified(
            model_id,
            model_provider="openrouter",
            base_url=base_url,
            **kwargs,
        )
    if s == "cerebras":
        return _get_cerebras_model(model_id, **kwargs)
    # Any other token (``cohere``, ``bedrock``, ``google_vertexai``, …): LangChain's catalog.
    return _init_chat_model_unified(
        model_id,
        model_provider=s,
        base_url=base_url,
        **kwargs,
    )


def _ambiguous_slash_model_help(model_id: str) -> str:
    return (
        f"Ambiguous model id {model_id!r} (contains '/'). "
        "Pick the backend explicitly — for example:\n"
        "  agloom -m groq:meta-llama/llama-4-scout-17b-16e-instruct\n"
        "  agloom --provider groq -m meta-llama/llama-4-scout-17b-16e-instruct\n"
        "  agloom -m ollama:llama3.2 [--base-url http://127.0.0.1:11434]\n"
        "  agloom -m litellm:groq/llama-3.3-70b-versatile\n"
        "  agloom -m cohere:command-r-plus\n"
        "  agloom -m lc:openrouter:anthropic/claude-3.5-sonnet\n"
        "Or set ai.provider in agloom.yaml. Docs: "
        "https://docs.langchain.com/oss/python/integrations/chat"
    )


def _route_slash_model(model_id: str, *, base_url: str | None, **kwargs: Any) -> Any:
    """Resolve ``org/model`` ids when no ``provider:`` prefix was used."""
    pref_raw = (os.environ.get("AGLOOM_PROVIDER") or "").strip()
    pref = pref_raw.lower().replace("-", "_")
    if (
        pref
        and pref not in _URI_SCHEME_PREFIXES
        and provider_slug_token_valid(pref_raw)
    ):
        if pref == "mistral":
            pref = "mistralai"
        return _get_by_provider(pref, model_id, base_url=base_url, **kwargs)

    has_ollama = bool(_default_ollama_base_url(None))
    has_groq = bool(os.environ.get("GROQ_API_KEY"))
    if has_ollama and has_groq:
        raise ValueError(
            _ambiguous_slash_model_help(model_id)
            + "\n\nBoth OLLAMA_BASE_URL/OLLAMA_HOST and GROQ_API_KEY are set — use "
            "`groq:…` / `ollama:…`, `--provider`, `ai.provider`, or `AGLOOM_PROVIDER`."
        )
    if has_groq:
        return _get_groq_model(model_id, **kwargs)
    if has_ollama:
        return _get_ollama_model(model_id, base_url=_default_ollama_base_url(base_url), **kwargs)

    raise ValueError(_ambiguous_slash_model_help(model_id))


def get_model(
    model_id: str,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> Any:
    """Get a LangChain chat model by ID (CLI routing + LiteLLM / ``init_chat_model`` bridges).

    First-party integrations are listed in ``pyproject.toml`` optional extras. For providers
    without a curated slug, use ``<provider>:<model_id>`` (``init_chat_model``), ``lc:…``, or
    ``litellm:…``. Install the integration from the LangChain provider index; keys may live in
    ``ai.api_keys`` in yaml (applied while the model is resolved).

    **Explicit routing**

    - ``provider`` kwarg or ``ai.provider`` from config forces the backend.
    - ``model_id`` may use ``provider:rest`` (e.g. ``groq:meta-llama/...``, ``litellm:groq/llama-3.1-8b-instant``).
    - ``base_url`` (or env ``OLLAMA_BASE_URL`` / ``OLLAMA_HOST``, ``VLLM_BASE_URL``) for local servers.
      For ``litellm``, ``base_url`` is passed as LiteLLM ``api_base``.

    Optional extras match ``[project.optional-dependencies]`` in ``pyproject.toml``.

    Args:
        model_id: Model identifier (optionally prefixed with ``provider:``).
        provider: Optional slug overriding heuristic routing (``groq``, ``ollama``, ``litellm``, …).
        base_url: Optional HTTP origin for ``ollama`` / ``vllm`` / OpenAI-compatible / LiteLLM endpoints.
        **kwargs: Decoding / client options from ``ai.llm``. Keys are normalized and filtered per
            provider (see :mod:`agloom_cli.llm_provider_params`).

    Returns:
        LangChain BaseChatModel instance
    """
    prefix_slug, rest = split_provider_prefix(model_id)
    mid = rest.strip() if prefix_slug else model_id.strip()
    merged_provider = (provider or prefix_slug or "").strip().lower() or None
    if merged_provider:
        merged_provider = merged_provider.replace("-", "_")
    if merged_provider == "mistral":
        merged_provider = "mistralai"
    if merged_provider:
        return _get_by_provider(merged_provider, mid, base_url=base_url, **kwargs)

    model_id_lower = mid.lower()

    if model_id_lower.startswith(("gpt-", "o1")):
        return _get_openai_model(mid, base_url=base_url, **kwargs)

    if "claude" in model_id_lower or model_id_lower.startswith("anthropic"):
        return _get_anthropic_model(mid, **kwargs)

    if "gemini" in model_id_lower or model_id_lower.startswith("models/gemini"):
        return _get_google_genai_model(mid, **kwargs)

    if "grok" in model_id_lower:
        return _get_xai_model(mid, **kwargs)

    if "groq" in model_id_lower:
        return _get_groq_model(mid, **kwargs)

    if "/" in mid and not model_id_lower.startswith(("openai/", "anthropic/")):
        return _route_slash_model(mid, base_url=base_url, **kwargs)

    if _looks_like_mistral_ai_cloud(mid):
        return _get_mistral_model(mid, **kwargs)

    if "llama" in model_id_lower or "mistral" in model_id_lower:
        ho, hg = bool(_default_ollama_base_url(None)), bool(os.environ.get("GROQ_API_KEY"))
        if ho and hg:
            raise ValueError(
                "Set either OLLAMA_BASE_URL for local models or GROQ_API_KEY for Groq — "
                "not both without choosing: use `groq:model`, `ollama:model`, or `AGLOOM_PROVIDER`."
            )
        if ho:
            return _get_ollama_model(mid, base_url=_default_ollama_base_url(base_url), **kwargs)
        if hg:
            return _get_groq_model(mid, **kwargs)
        raise ValueError(
            f"Could not resolve {mid!r}. Export GROQ_API_KEY, or set OLLAMA_BASE_URL and "
            "`pip install 'agloom[ollama]'`, or use an explicit prefix e.g. `groq:{mid}`."
        )

    return _get_default_model(mid, **kwargs)


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


def try_resolve_llm_from_api_keys(*, interactive: bool | None = None, **llm_kwargs: Any) -> Any | None:
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
                return get_model(default_model, **llm_kwargs)

    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if len(usable) == 1:
        return get_model(usable[0][2], **llm_kwargs)

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
        return get_model(usable[idx][2], **llm_kwargs)

    return get_model(usable[0][2], **llm_kwargs)


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
    if "litellm" in cls_name:
        return "litellm", mid_s
    if "cerebras" in cls_name:
        return "cerebras", mid_s
    return type(llm).__name__.replace("Chat", "").lower() or "llm", mid_s


def _get_vllm_openai_compatible(model_id: str, *, base_url: str | None = None, **kwargs: Any) -> Any:
    """vLLM HTTP server (OpenAI-compatible). See LangChain + vLLM docs."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise MissingProviderDependency("openai", "'agloom[openai]'") from e

    bu = _default_vllm_base_url(base_url)
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VLLM_API_KEY") or "EMPTY"
    opts = spread_llm_options_for_provider("vllm", kwargs)
    if "temperature" not in opts:
        opts["temperature"] = kwargs.get("temperature", 0)
    return ChatOpenAI(
        model=model_id,
        base_url=bu,
        api_key=api_key,
        **opts,
    )


def _get_openai_model(model_id: str, *, base_url: str | None = None, **kwargs: Any) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise MissingProviderDependency("openai", "'agloom[openai]'") from e

    params: dict[str, Any] = {
        "model": model_id,
        "api_key": _require_env("OPENAI_API_KEY", for_provider="OpenAI"),
        **spread_llm_options_for_provider("openai", kwargs),
    }
    if "temperature" not in params:
        params["temperature"] = kwargs.get("temperature", 0)
    if base_url:
        params["base_url"] = base_url.strip()
    return ChatOpenAI(**params)


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

    opts = spread_llm_options_for_provider("anthropic", kwargs)
    if "temperature" not in opts:
        opts["temperature"] = kwargs.get("temperature", 0)
    return ChatAnthropic(
        model=actual_model,
        anthropic_api_key=_require_env("ANTHROPIC_API_KEY", for_provider="Anthropic"),
        **opts,
    )


def _get_google_genai_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise MissingProviderDependency("google-genai", "'agloom[google-genai]'") from e

    key = _require_google_api_key()
    opts = spread_llm_options_for_provider("google", kwargs)
    if "temperature" not in opts:
        opts["temperature"] = kwargs.get("temperature", 0)
    return ChatGoogleGenerativeAI(
        model=model_id,
        api_key=key,
        **opts,
    )


def _get_mistral_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_mistralai import ChatMistralAI
    except ImportError as e:
        raise MissingProviderDependency("mistralai", "'agloom[mistralai]'") from e

    opts = spread_llm_options_for_provider("mistralai", kwargs)
    if "temperature" not in opts:
        opts["temperature"] = kwargs.get("temperature", 0)
    return ChatMistralAI(
        model=model_id,
        api_key=_require_env("MISTRAL_API_KEY", for_provider="Mistral AI"),
        **opts,
    )


def _get_xai_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_xai import ChatXAI
    except ImportError as e:
        raise MissingProviderDependency("xai", "'agloom[xai]'") from e

    opts = spread_llm_options_for_provider("xai", kwargs)
    if "temperature" not in opts:
        opts["temperature"] = kwargs.get("temperature", 0)
    return ChatXAI(
        model=model_id,
        api_key=_require_env("XAI_API_KEY", for_provider="xAI"),
        **opts,
    )


def _get_cerebras_model(model_id: str, **kwargs) -> Any:
    """Cerebras — not in LangChain ``_BUILTIN_PROVIDERS``; use first-party package."""
    try:
        from langchain_cerebras import ChatCerebras
    except ImportError as e:
        raise MissingProviderDependency("cerebras", "'agloom[cerebras]'") from e

    opts = spread_llm_options_for_provider("cerebras", kwargs)
    if "temperature" not in opts:
        opts["temperature"] = kwargs.get("temperature", 0)
    return ChatCerebras(
        model=model_id,
        api_key=_require_env("CEREBRAS_API_KEY", for_provider="Cerebras"),
        **opts,
    )


def _get_groq_model(model_id: str, **kwargs) -> Any:
    try:
        from langchain_groq import ChatGroq
    except ImportError as e:
        raise MissingProviderDependency("groq", "'agloom[groq]'") from e

    opts = spread_llm_options_for_provider("groq", kwargs)
    if "temperature" not in opts:
        opts["temperature"] = kwargs.get("temperature", 0)
    return ChatGroq(
        model=model_id,
        api_key=_require_env("GROQ_API_KEY", for_provider="Groq"),
        **opts,
    )


def _get_ollama_model(model_id: str, *, base_url: str | None = None, **kwargs: Any) -> Any:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise MissingProviderDependency("ollama", "'agloom[ollama]'") from e

    params: dict[str, Any] = {
        "model": model_id,
        **spread_llm_options_for_provider("ollama", kwargs),
    }
    if "temperature" not in params:
        params["temperature"] = kwargs.get("temperature", 0)
    if base_url:
        params["base_url"] = base_url.strip()
    return ChatOllama(**params)


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
