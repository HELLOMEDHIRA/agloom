"""Model resolution — route model ids and config to LangChain chat models.

Used by :func:`create_agent`, :func:`get_model`, YAML-loaded patches, and the AGP runtime when it
needs a default LLM from environment keys. Clients (agloom CLI, web workspace, custom drivers) do not implement
their own routing; they pass through the same ``model`` / ``provider`` strings this module accepts.

LangChain integrations index:
https://docs.langchain.com/oss/python/integrations/chat
Full provider list:
https://docs.langchain.com/oss/python/integrations/providers/all_providers

**Explicit provider prefix** (recommended for ids such as ``meta-llama/...``):

- Python: ``await create_agent(model="groq:meta-llama/llama-4-scout-17b-16e-instruct", ...)``
- Config: ``ai.provider: groq`` with ``ai.model: meta-llama/...``, optional ``ai.base_url``.
- Local Ollama: ``model="ollama:llama3.2"`` plus ``base_url`` (or ``OLLAMA_BASE_URL``).

**Broad routing** (install the matching optional extra from ``pyproject.toml``):

- **LiteLLM**: ``model="litellm:groq/llama-3.3-70b-versatile"`` or ``ai.provider: litellm`` +
  ``ai.model: …``; ``base_url`` maps to LiteLLM ``api_base``.
- **Unified initializer** (same as ``langchain.chat_models.init_chat_model``): ``model="lc:openai:gpt-4o"``
  or ``model="init:groq:meta-llama/..."`` — requires the right ``langchain-*`` extra (e.g.
  ``agloom[openai]``, ``agloom[groq]``).
- **OpenRouter**: ``model="openrouter:anthropic/claude-3.5-sonnet"`` (needs ``agloom[openrouter]``).

``vLLM`` and other OpenAI-compatible servers use ``ChatOpenAI`` + ``base_url``:
https://docs.langchain.com/oss/python/integrations/chat/vllm

``pyproject.toml`` defines optional extras ``agloom[<name>]`` for each first-party package (plus
``community`` for long-tail models). Example: ``pip install 'agloom[openai,groq,ollama,litellm]'``.
Curated slugs keep strict API-key checks; any other ``provider:model`` token routes to
``init_chat_model`` per the LangChain provider list (install the matching extra or ``agloom[community]``).
Use ``litellm:…`` for LiteLLM’s router, or ``lc:`` / ``init:`` for a full prefixed descriptor.

When several API keys are set and no ``AGLOOM_PROVIDER`` is chosen, :func:`try_resolve_llm_from_api_keys`
may prompt on an interactive TTY; non-interactive callers (including ``agloom-runtime``) use a fixed
priority order instead.
"""

from __future__ import annotations

import os
import re
import sys
from importlib import util
from typing import Any

from agloom.llm.llm_provider_params import normalize_provider_slug, spread_llm_options_for_provider
from agloom.llm.provider_registry import (
    CLASS_TO_SLUG,
    PROVIDERS,
    cli_auto_detect_rows,
)
from agloom.llm.provider_registry import (
    PROVIDER_ENV_KEYS as _PROVIDER_ENV_KEYS,
)
from agloom.llm.provider_registry import (
    SLUG_TO_CHAT_MODULE as _SLUG_TO_IMPORT,
)
from agloom.llm.provider_registry import (
    SLUG_TO_PIP_EXTRA as _SLUG_TO_EXTRA,
)


def _slug_for_spread_llm(*, model_provider: str | None, model: str) -> str:
    """Provider slug for :func:`spread_llm_options_for_provider` when using ``init_chat_model``."""
    if model_provider:
        return normalize_provider_slug(model_provider)
    pref, _rest = split_provider_prefix(model)
    if pref and pref not in ("lc", "init"):
        return normalize_provider_slug(pref)
    return "__generic_init__"

# Rows for env-key auto-detect (slug, label, env keys tuple, default model) from :mod:`agloom.llm.provider_registry`.
_ENV_AUTODETECT_ROWS = cli_auto_detect_rows()


def augment_patch_api_keys_from_env(patch: dict[str, Any]) -> dict[str, Any]:
    """Add ``api_keys`` from :func:`os.environ` for the resolved provider without clobbering *patch*.

    Keys already present in *patch* win; we only ``setdefault`` from :func:`os.environ` so YAML can
    stay portable while still picking up exported secrets.
    """
    model = str(patch.get("model") or "").strip()
    prov_hint = patch.get("provider")
    if isinstance(prov_hint, str):
        prov_hint = prov_hint.strip() or None
    pref, _rest = split_provider_prefix(model)
    raw_tok = (pref or prov_hint or "").strip()
    # Canonical slug: shared with params filtering (folds google_genai → google, etc.).
    canon = normalize_provider_slug(raw_tok) if raw_tok else ""
    keys_tpl = _PROVIDER_ENV_KEYS.get(canon, ())
    snap: dict[str, str] = {}
    for name in keys_tpl:
        v = os.environ.get(name)
        if v and v.strip():
            snap[name] = v.strip()
    if not snap:
        return patch
    merged = dict(patch.get("api_keys") or {})
    for k, v in snap.items():
        merged.setdefault(k, v)
    out = dict(patch)
    out["api_keys"] = merged
    return out

# ``_SLUG_TO_EXTRA`` and ``_SLUG_TO_IMPORT`` are imported from :mod:`agloom.llm.provider_registry`.

# URI schemes: first ``:`` is not ``provider:model`` (avoids ``https://...`` false splits).
_URI_SCHEME_PREFIXES: frozenset[str] = frozenset({"http", "https", "file", "urn", "data", "ftp"})
# Provider token for ``slug:model_id`` (matches LangChain ``model_provider`` / LiteLLM-style slugs).
_PROVIDER_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

_CLOUD_IAM_SLUGS: frozenset[str] = frozenset(
    {"bedrock", "google_vertexai", "google_anthropic_vertex", "snowflake"},
)


def _levenshtein(a: str, b: str) -> int:
    """Classic O(len(a)*len(b)) edit distance (lowercase ASCII tokens)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins, delete, sub = cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _curated_provider_slug_pool() -> frozenset[str]:
    """Canonical + alias slugs used for typo detection (curated registry only)."""
    out: set[str] = set()
    for p in PROVIDERS.values():
        out.add(p.slug)
        for alias in p.aliases:
            out.add(normalize_provider_slug(alias))
    return frozenset(out)


def suggest_typo_provider_slug(raw: str) -> str | None:
    """If *raw* is likely a typo of a curated provider slug, return the correction."""
    s = normalize_provider_slug(raw)
    pool = _curated_provider_slug_pool()
    if s in pool:
        return None
    best_d = 10**9
    matches: list[str] = []
    for cand in sorted(pool):
        d = _levenshtein(s, cand)
        if d < best_d:
            best_d = d
            matches = [cand]
        elif d == best_d:
            matches.append(cand)
    if best_d > 2 or len(matches) != 1:
        return None
    return matches[0]


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
    """Optional LangChain provider package is not installed (``agloom[extra]``).

    **Handling policy**

    Application entrypoints (library callers, runtimes, or frontends) should catch this and
    surface the ``pip_hint`` / ``extra`` string instead of a raw import traceback.

    Always re-raise or replace with a clearer error — never swallow silently.
    """

    def __init__(self, extra: str, pip_hint: str, *, detail: str | None = None) -> None:
        self.extra = extra
        self.pip_hint = pip_hint
        if detail is not None:
            super().__init__(detail)
            return
        if extra == "langchain":
            super().__init__(f"LangChain is not installed. Example: pip install {pip_hint}")
            return
        lc = _extra_to_langchain_dist(extra)
        super().__init__(f"{lc} not installed. Run: pip install {pip_hint}")


def _extra_to_langchain_dist(extra: str) -> str:
    """Map ``pyproject`` optional extra name to the usual LangChain wheel on PyPI."""
    e = extra.replace("_", "-")
    if e.startswith("langchain"):
        return e
    return f"langchain-{e}"


class MissingProviderApiKey(ValueError):
    """Required API key for the resolved provider is not set (avoid SDK tracebacks).

    **Handling policy**: same idea as :class:`MissingProviderDependency` — surface which
    environment variable is missing before touching the provider SDK.
    """


def _require_env(name: str, *, for_provider: str) -> str:
    v = os.environ.get(name)
    if v:
        return v
    raise MissingProviderApiKey(
        f"{name} not set. Set it in your shell or pass --api-key-env {name} "
        f"(with the var pointing at your key)."
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
    # Canonicalize via the same table the params filter uses — so wizard-saved patches
    # (e.g. ``google_genai:gemini-...``) hit the curated path and get the full param surface.
    s = normalize_provider_slug(slug)
    if s not in ("lc", "init") and s not in PROVIDERS:
        tip = suggest_typo_provider_slug(s)
        if tip:
            raise ValueError(
                f"unknown provider {s!r} — did you mean {tip!r}? Run `agloom --list-providers`."
            )
    if s == "google":
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
        '  create_agent(model="groq:meta-llama/llama-4-scout-17b-16e-instruct", ...)\n'
        '  create_agent(model="meta-llama/...", provider="groq", ...)\n'
        '  create_agent(model="ollama:llama3.2", base_url="http://127.0.0.1:11434", ...)\n'
        '  create_agent(model="litellm:groq/llama-3.3-70b-versatile", ...)\n'
        '  create_agent(model="cohere:command-r-plus", ...)\n'
        '  create_agent(model="lc:openrouter:anthropic/claude-3.5-sonnet", ...)\n'
        "Or set ``ai.provider`` / ``ai.model`` in agloom.yaml (or ``AGLOOM_PROVIDER``). Docs: "
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
            "`groq:…` / `ollama:…` prefixes, pass ``provider=``, set ``ai.provider``, or ``AGLOOM_PROVIDER``."
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
    """Get a LangChain chat model by ID (curated slugs + LiteLLM / ``init_chat_model`` bridges).

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
            provider (see :mod:`agloom.llm.llm_provider_params`).

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


def _usable_provider_triples() -> tuple[list[tuple[str, str, str]], list[MissingProviderDependency]]:
    """Providers with env key(s) set **and** integration importable → one ``get_model`` call each later."""
    usable: list[tuple[str, str, str]] = []
    missing: list[MissingProviderDependency] = []
    for slug, label, env_spec, default_model in _ENV_AUTODETECT_ROWS:
        if not _env_configured(env_spec):
            continue
        if not _integration_importable(slug):
            ex, hint = _SLUG_TO_EXTRA[slug]
            missing.append(MissingProviderDependency(ex, hint))
            continue
        usable.append((slug, label, default_model))
    return usable, missing


def try_resolve_llm_from_api_keys(*, interactive: bool | None = None, **llm_kwargs: Any) -> Any | None:
    """Pick a default model from API keys (e.g. ``agloom-runtime`` bootstrapping without an explicit model).

    - If exactly one provider is usable (key set + extra installed), use it.
    - If several are usable and stdin/stdout are TTYs, prompt for a choice (override with ``AGLOOM_PROVIDER``).
    - If several are usable but not interactive, use the first row in registry auto-detect priority order.

    Skips providers whose optional packages are not installed.
    """
    usable, missing_for_configured_keys = _usable_provider_triples()
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
        slug_hint = ", ".join(s for s, _, __ in usable)
        sys.stderr.write(
            "\nMultiple LLM API keys detected. Choose a provider "
            f"(or set AGLOOM_PROVIDER to one of: {slug_hint})\n\n",
        )
        for i, (slug, label, default_model) in enumerate(usable, start=1):
            sys.stderr.write(f"  {i}. {label} ({slug}) — default model {default_model}\n")
        idx = 0
        while True:
            raw = input("Enter number [1]: ").strip() or "1"
            try:
                choice = int(raw)
            except ValueError:
                sys.stderr.write("Invalid number; enter an integer.\n")
                continue
            if 1 <= choice <= len(usable):
                idx = choice - 1
                break
            sys.stderr.write(f"Enter a number from 1 to {len(usable)}.\n")
        return get_model(usable[idx][2], **llm_kwargs)

    return get_model(usable[0][2], **llm_kwargs)


def describe_llm(llm: Any) -> tuple[str, str]:
    """Return ``(provider_slug, model_id)`` for status lines (e.g. REPL INFO panel).

    Uses :data:`agloom.llm.provider_registry.CLASS_TO_SLUG` for an exact class-name lookup;
    falls back to substring matching so wrappers / forks (e.g. ``MyChatGroq``) still resolve.
    """
    cls_name = type(llm).__name__
    mid = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    mid_s = str(mid).strip() if mid else "auto"

    # Fast path: exact LangChain class match.
    slug = CLASS_TO_SLUG.get(cls_name)
    if slug:
        return slug, mid_s

    # Slow path: substring match for wrappers / renames. Order matters — more-specific
    # tokens (``grok``, ``claude``) are checked before short ones (``openai``).
    cls_lower = cls_name.lower()
    for token, fallback_slug in (
        ("groq", "groq"),
        ("anthropic", "anthropic"),
        ("claude", "anthropic"),
        ("gemini", "google"),
        ("google", "google"),
        ("mistral", "mistralai"),
        ("grok", "xai"),
        ("xai", "xai"),
        ("ollama", "ollama"),
        ("litellm", "litellm"),
        ("cerebras", "cerebras"),
        ("openai", "openai"),
    ):
        if token in cls_lower:
            return fallback_slug, mid_s

    return cls_name.replace("Chat", "").lower() or "llm", mid_s


def merged_provider_parts(
    model_id: str,
    *,
    provider: str | None = None,
) -> tuple[str | None, str, str | None]:
    """Return ``(merged_slug_or_none, model_rest, split_prefix)`` — mirrors :func:`get_model` routing."""
    prefix_slug, rest = split_provider_prefix(model_id.strip())
    mid = rest.strip() if prefix_slug else model_id.strip()
    merged_provider = (provider or prefix_slug or "").strip().lower() or None
    if merged_provider:
        merged_provider = merged_provider.replace("-", "_")
    if merged_provider == "mistral":
        merged_provider = "mistralai"
    return merged_provider, mid, prefix_slug


def print_providers_table_text(*, file: Any = None) -> None:
    """Print all curated rows from :data:`~agloom.llm.provider_registry.PROVIDERS`."""
    sink = file or sys.stdout
    rows = sorted(PROVIDERS.values(), key=lambda p: p.slug)
    sink.write(f"{'slug':<26} {'label':<24} {'default_model':<44} {'env_keys':<40} pip_extra\n")
    for p in rows:
        env = ", ".join(p.resolver_env_keys) if p.resolver_env_keys else "(cloud IAM / none)"
        extra = f"agloom[{p.pip_extra}]" if p.pip_extra else "-"
        dm = p.default_model if len(p.default_model) <= 42 else p.default_model[:41] + "…"
        sink.write(f"{p.slug:<26} {p.label:<24} {dm:<44} {env:<40} {extra}\n")


def describe_resolve_dry_text(spec: str, *, provider: str | None = None) -> str:
    """Human-readable dry-run of how *spec* routes (no LLM construction)."""
    merged, mid, pref = merged_provider_parts(spec, provider=provider)
    lines: list[str] = [f"spec: {spec!r}"]
    if provider:
        lines.append(f"--provider override: {provider!r}")
    lines.append(f"split_prefix: {pref!r}")
    lines.append(f"model_id (after split): {mid!r}")
    if not merged:
        lines.append(
            "routing: unprefixed — get_model uses heuristics (name tokens, slash ids, env keys); "
            "use an explicit prefix or AGLOOM_PROVIDER for deterministic routing.",
        )
        return "\n".join(lines)

    slug = normalize_provider_slug(merged)
    lines.append(f"resolved_provider_slug: {slug}")

    if slug in ("lc", "init"):
        lines.append("routing: langchain.chat_models.init_chat_model (lc/init unified initializer)")
        lines.append(f"nested_descriptor: {mid!r}")
        lines.append("integration: install the matching langchain-* extra for the inner provider token.")
        return "\n".join(lines)

    info = PROVIDERS.get(slug)
    if info:
        lines.append(f"label: {info.label}")
        lines.append(f"chat_module: {info.chat_module or '(resolved via init_chat_model / provider package)'}")
        lines.append(f"chat_class: {info.chat_class or '(varies by LangChain version)'}")
        if slug in _CLOUD_IAM_SLUGS:
            if slug == "bedrock":
                lines.append(
                    "auth: Amazon Bedrock requires AWS credentials via `aws configure` or "
                    "environment / IAM role — no API key flag needed.",
                )
            elif slug in ("google_vertexai", "google_anthropic_vertex"):
                lines.append(
                    "auth: Vertex uses Application Default Credentials "
                    "(gcloud auth application-default login or GOOGLE_APPLICATION_CREDENTIALS).",
                )
            elif slug == "snowflake":
                lines.append(
                    "auth: Snowflake Cortex uses Snowflake session parameters / connectors — "
                    "see langchain-snowflake docs.",
                )
        elif info.resolver_env_keys:
            lines.append("env_keys (registry):")
            for k in info.resolver_env_keys:
                raw = os.environ.get(k)
                ok = bool(raw and raw.strip())
                lines.append(f"  {k}: {'set' if ok else 'unset'}")
        else:
            lines.append("auth: no API keys listed in registry (often local HTTP, e.g. Ollama).")
        pip = f"agloom[{info.pip_extra}]" if info.pip_extra else "(see upstream docs)"
        lines.append(f"pip_extra hint: {pip}")
        return "\n".join(lines)

    lines.append("routing: LangChain init_chat_model (slug not in curated PROVIDERS table)")
    tip = suggest_typo_provider_slug(slug)
    if tip:
        lines.append(f"typo_hint: did you mean {tip!r}? Try `agloom --list-providers`.")
    return "\n".join(lines)


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
    """Route an unprefixed model id (or ``auto``) to the first provider with an env key set.

    When *model_id* is ``auto`` / empty, substitute a curated default for the picked provider.
    Otherwise honor the user's id (likely a custom fine-tune / deployment name) — let the SDK
    reject it if invalid rather than silently swapping it for the curated default.
    """
    mid = (model_id or "").strip()
    use_curated = (not mid) or mid.lower() == "auto"

    if os.environ.get("OPENAI_API_KEY"):
        return _get_openai_model("gpt-4o" if use_curated else mid, **kwargs)

    if os.environ.get("ANTHROPIC_API_KEY"):
        return _get_anthropic_model("claude-3-5-sonnet-20241022" if use_curated else mid, **kwargs)

    if _google_api_key():
        return _get_google_genai_model("gemini-2.0-flash" if use_curated else mid, **kwargs)

    if os.environ.get("MISTRAL_API_KEY"):
        return _get_mistral_model("mistral-large-latest" if use_curated else mid, **kwargs)

    if os.environ.get("GROQ_API_KEY"):
        return _get_groq_model(
            "meta-llama/llama-4-scout-17b-16e-instruct" if use_curated else mid,
            **kwargs,
        )

    if os.environ.get("XAI_API_KEY"):
        return _get_xai_model("grok-3-latest" if use_curated else mid, **kwargs)

    raise ValueError(
        "No model found. Set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY or GEMINI_API_KEY, "
        "MISTRAL_API_KEY, GROQ_API_KEY, XAI_API_KEY"
    )
