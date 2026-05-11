"""Canonical provider registry — single source of truth for LLM provider metadata.

Consumers under :mod:`agloom.llm` derive env-key tables, pip-extra hints, and constructor
filters from :data:`PROVIDERS`:

- :mod:`agloom.llm.model_resolver` — routing, env snapshots, optional-interactive resolution
- :mod:`agloom.llm.llm_provider_params` — YAML-friendly kwargs → LangChain constructor fields

Add a provider once here; derived tables update automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final


@dataclass(frozen=True)
class ProviderInfo:
    """Canonical provider metadata.

    ``slug`` is the post-:func:`agloom.llm.llm_provider_params.normalize_provider_slug` form used
    by the resolver / params filter. ``wizard_aliases`` lists *all* slugs the wizard menu may
    surface for this provider (e.g. ``("bedrock", "bedrock_converse", "anthropic_bedrock")``);
    each becomes a row keyed by that alias in the wizard's lookup tables. If empty, ``slug`` is
    used as the only alias.

    ``primary_env_key`` is what the wizard prompts for (one key); ``extra_env_keys`` are also
    accepted by the resolver when snapshotting environment values into a session JSON.
    Cloud-IAM providers (Bedrock, Vertex, Snowflake) leave both ``None`` / empty.
    """

    slug: str
    label: str
    default_model: str
    wizard_aliases: tuple[str, ...] = ()
    primary_env_key: str | None = None
    extra_env_keys: tuple[str, ...] = ()
    pip_extra: str | None = None
    chat_module: str | None = None
    chat_class: str | None = None
    auto_priority: int | None = None

    @property
    def aliases(self) -> tuple[str, ...]:
        """All wizard aliases (defaults to ``(slug,)`` when ``wizard_aliases`` is empty)."""
        return self.wizard_aliases or (self.slug,)

    @property
    def resolver_env_keys(self) -> tuple[str, ...]:
        """Full env-key set the resolver snapshots (primary + extras), or ``()`` for cloud IAM."""
        if not self.primary_env_key:
            return ()
        return (self.primary_env_key, *self.extra_env_keys)


def _p(*args, **kwargs) -> ProviderInfo:
    return ProviderInfo(*args, **kwargs)


# Curated providers — kept in a list so insertion order survives Python dict ordering.
# Order does NOT control auto-detect priority; that's set explicitly via ``auto_priority``.
_PROVIDER_LIST: Final[tuple[ProviderInfo, ...]] = (
    _p(
        slug="openai",
        label="OpenAI",
        default_model="gpt-4o",
        primary_env_key="OPENAI_API_KEY",
        pip_extra="openai",
        chat_module="langchain_openai",
        chat_class="ChatOpenAI",
        auto_priority=1,
    ),
    _p(
        slug="anthropic",
        label="Anthropic",
        default_model="claude-3-5-sonnet-20241022",
        primary_env_key="ANTHROPIC_API_KEY",
        pip_extra="anthropic",
        chat_module="langchain_anthropic",
        chat_class="ChatAnthropic",
        auto_priority=2,
    ),
    _p(
        slug="google",
        label="Google Gemini",
        default_model="gemini-2.0-flash",
        wizard_aliases=("google_genai",),  # LangChain registers Gemini as ``google_genai``
        primary_env_key="GOOGLE_API_KEY",
        extra_env_keys=("GEMINI_API_KEY",),
        pip_extra="google-genai",
        chat_module="langchain_google_genai",
        chat_class="ChatGoogleGenerativeAI",
        auto_priority=3,
    ),
    _p(
        slug="mistralai",
        label="Mistral AI",
        default_model="mistral-large-latest",
        primary_env_key="MISTRAL_API_KEY",
        pip_extra="mistralai",
        chat_module="langchain_mistralai",
        chat_class="ChatMistralAI",
        auto_priority=4,
    ),
    _p(
        slug="groq",
        label="Groq",
        default_model="meta-llama/llama-4-scout-17b-16e-instruct",
        primary_env_key="GROQ_API_KEY",
        pip_extra="groq",
        chat_module="langchain_groq",
        chat_class="ChatGroq",
        auto_priority=5,
    ),
    _p(
        slug="xai",
        label="xAI",
        default_model="grok-3-latest",
        primary_env_key="XAI_API_KEY",
        pip_extra="xai",
        chat_module="langchain_xai",
        chat_class="ChatXAI",
        auto_priority=6,
    ),
    _p(
        slug="ollama",
        label="Ollama",
        default_model="llama3.2",
        # Ollama uses HTTP (no API key); resolver and wizard both leave env keys empty.
        pip_extra="ollama",
        chat_module="langchain_ollama",
        chat_class="ChatOllama",
    ),
    _p(
        slug="vllm",
        label="vLLM",
        default_model="meta-llama/Llama-3-8b-instruct",
        primary_env_key="OPENAI_API_KEY",  # OpenAI-compatible HTTP server
        extra_env_keys=("VLLM_API_KEY",),
        pip_extra="openai",  # uses ChatOpenAI + base_url
        chat_module="langchain_openai",
    ),
    _p(
        slug="litellm",
        label="LiteLLM",
        default_model="groq/llama-3.3-70b-versatile",
        primary_env_key="OPENAI_API_KEY",
        pip_extra="litellm",
        chat_module="langchain_litellm",
        chat_class="ChatLiteLLM",
    ),
    _p(
        slug="openrouter",
        label="OpenRouter",
        default_model="openai/gpt-4o",
        primary_env_key="OPENROUTER_API_KEY",
        pip_extra="openrouter",
        chat_module="langchain_openrouter",
    ),
    _p(
        slug="cerebras",
        label="Cerebras",
        default_model="llama-3.3-70b",
        primary_env_key="CEREBRAS_API_KEY",
        pip_extra="cerebras",
        chat_module="langchain_cerebras",
        chat_class="ChatCerebras",
    ),
    _p(
        slug="nvidia",
        label="NVIDIA NIM",
        default_model="meta/llama3-70b-instruct",
        primary_env_key="NVIDIA_API_KEY",
        pip_extra="nvidia",
        chat_module="langchain_nvidia_ai_endpoints",
        chat_class="ChatNVIDIA",
    ),
    _p(
        slug="cohere",
        label="Cohere",
        default_model="command-r-plus",
        primary_env_key="COHERE_API_KEY",
        pip_extra="cohere",
        chat_module="langchain_cohere",
        chat_class="ChatCohere",
    ),
    _p(
        slug="deepseek",
        label="DeepSeek",
        default_model="deepseek-chat",
        primary_env_key="DEEPSEEK_API_KEY",
        pip_extra="deepseek",
        chat_module="langchain_deepseek",
        chat_class="ChatDeepSeek",
    ),
    _p(
        slug="fireworks",
        label="Fireworks AI",
        default_model="accounts/fireworks/models/llama-v3p1-8b-instruct",
        primary_env_key="FIREWORKS_API_KEY",
        pip_extra="fireworks",
        chat_module="langchain_fireworks",
        chat_class="ChatFireworks",
    ),
    _p(
        slug="together",
        label="Together AI",
        default_model="meta-llama/Llama-3-70b-chat-hf",
        primary_env_key="TOGETHER_API_KEY",
        pip_extra="together",
        chat_module="langchain_together",
        chat_class="ChatTogether",
    ),
    _p(
        slug="perplexity",
        label="Perplexity",
        default_model="sonar",
        primary_env_key="PERPLEXITY_API_KEY",
        pip_extra="perplexity",
        chat_module="langchain_perplexity",
        chat_class="ChatPerplexity",
    ),
    _p(
        slug="upstage",
        label="Upstage",
        default_model="solar-1-mini-chat",
        primary_env_key="UPSTAGE_API_KEY",
        pip_extra="upstage",
        chat_module="langchain_upstage",
        chat_class="ChatUpstage",
    ),
    _p(
        slug="ibm",
        label="IBM Watsonx",
        default_model="ibm/granite-3-2-8b-instruct",
        primary_env_key="WATSONX_API_KEY",
        pip_extra="ibm",
        chat_module="langchain_ibm",
        chat_class="ChatWatsonx",
    ),
    _p(
        slug="huggingface",
        label="Hugging Face",
        default_model="HuggingFaceH4/zephyr-7b-beta",
        primary_env_key="HUGGINGFACEHUB_API_TOKEN",
        pip_extra="huggingface",
        chat_module="langchain_huggingface",
        chat_class="ChatHuggingFace",
    ),
    _p(
        slug="baseten",
        label="Baseten",
        default_model="llama-3-8b",
        primary_env_key="BASETEN_API_KEY",
        # Baseten ships its own ``langchain-*`` package outside our pyproject extras.
    ),
    _p(
        slug="azure_openai",
        label="Azure OpenAI",
        default_model="gpt-4o",
        primary_env_key="AZURE_OPENAI_API_KEY",
        extra_env_keys=("AZURE_OPENAI_ENDPOINT",),
        pip_extra="openai",  # AzureChatOpenAI ships in langchain-openai
        chat_module="langchain_openai",
        chat_class="AzureChatOpenAI",
    ),
    _p(
        slug="azure_ai",
        label="Azure AI",
        default_model="gpt-4o",
        primary_env_key="AZURE_AI_API_KEY",
        extra_env_keys=("AZURE_AI_ENDPOINT",),
        pip_extra="azure-ai",
        chat_module="langchain_azure_ai",
    ),
    _p(
        slug="bedrock",
        label="Amazon Bedrock",
        default_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        wizard_aliases=("bedrock", "bedrock_converse", "anthropic_bedrock"),
        # Cloud IAM (AWS CLI / IRSA) — no env key prompt.
        pip_extra="aws",
        chat_module="langchain_aws",
        chat_class="ChatBedrock",
    ),
    _p(
        slug="google_vertexai",
        label="Google Vertex AI",
        default_model="gemini-2.0-flash",
        # Cloud IAM (gcloud / ADC) — no env key prompt.
        pip_extra="google-vertexai",
        chat_module="langchain_google_vertexai",
        chat_class="ChatVertexAI",
    ),
    _p(
        slug="google_anthropic_vertex",
        label="Anthropic on Vertex",
        default_model="claude-3-5-sonnet@20240620",
        # Cloud IAM — no env key prompt.
        chat_module="langchain_google_vertexai",
    ),
    _p(
        slug="sambanova",
        label="SambaNova",
        default_model="Meta-Llama-3.3-70B-Instruct",
        primary_env_key="SAMBANOVA_API_KEY",
        pip_extra="sambanova",
        chat_module="langchain_sambanova",
        chat_class="ChatSambaNovaCloud",
    ),
    _p(
        slug="snowflake",
        label="Snowflake Cortex",
        default_model="snowflake-arctic",
        # Snowflake auth (account/user/password or PAT) is too varied to snapshot generically.
        pip_extra="snowflake",
        chat_module="langchain_snowflake",
        chat_class="ChatSnowflakeCortex",
    ),
)

PROVIDERS: Final[dict[str, ProviderInfo]] = {p.slug: p for p in _PROVIDER_LIST}


def provider_catalog() -> list[dict[str, Any]]:
    """Ordered rows for AGP ``runtime.providers`` / UIs (slug, label, default model, env hint)."""

    return [
        {
            "slug": p.slug,
            "label": p.label,
            "default_model": p.default_model,
            "primary_env_key": p.primary_env_key,
        }
        for p in _PROVIDER_LIST
    ]
"""Canonical-slug → :class:`ProviderInfo` mapping. Sole source of truth."""


# ── Derived tables (computed once at import; immutable). ─────────────────────

PROVIDER_ENV_KEYS: Final[dict[str, tuple[str, ...]]] = {
    p.slug: p.resolver_env_keys for p in _PROVIDER_LIST if p.resolver_env_keys
}
"""Canonical slug → tuple of env vars the resolver snapshots into ``ai.api_keys``.

Cloud-IAM providers (Bedrock, Vertex, Snowflake) are deliberately omitted (would be ``()``).
"""


def _build_wizard_env_keys() -> dict[str, list[str]]:
    """Wizard alias → list of one env key to prompt for (or ``[]`` for cloud IAM)."""
    out: dict[str, list[str]] = {}
    for p in _PROVIDER_LIST:
        prompt_list = [p.primary_env_key] if p.primary_env_key else []
        for alias in p.aliases:
            out[alias] = list(prompt_list)
    return out


WIZARD_ENV_KEYS: Final[dict[str, list[str]]] = _build_wizard_env_keys()
"""Wizard alias → single-element prompt list (or empty for cloud IAM).

The resolver uses :data:`PROVIDER_ENV_KEYS` (canonical slug, full key set) for snapshotting;
the wizard only needs one prompt per provider.
"""


def _build_default_models() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in _PROVIDER_LIST:
        for alias in p.aliases:
            out[alias] = p.default_model
    return out


WIZARD_DEFAULT_MODELS: Final[dict[str, str]] = _build_default_models()
"""Wizard alias → curated default model id."""


def cli_auto_detect_rows() -> list[tuple[str, str, tuple[str, ...], str]]:
    """Auto-pick rows ``(canonical_slug, label, env_check_tuple, default_model)``.

    Sorted by ``auto_priority`` ascending; only includes providers with that field set.
    """
    rows = [p for p in _PROVIDER_LIST if p.auto_priority is not None]
    rows.sort(key=lambda p: p.auto_priority or 0)
    return [(p.slug, p.label, p.resolver_env_keys, p.default_model) for p in rows]


SLUG_TO_PIP_EXTRA: Final[dict[str, tuple[str, str]]] = {
    p.slug: (p.pip_extra, f"'agloom[{p.pip_extra}]'") for p in _PROVIDER_LIST if p.pip_extra
}
"""Canonical slug → ``(pip-extra-name, install-hint)`` for ``MissingProviderDependency`` messages."""


SLUG_TO_CHAT_MODULE: Final[dict[str, str]] = {
    p.slug: p.chat_module for p in _PROVIDER_LIST if p.chat_module
}
"""Canonical slug → ``langchain-*`` Python module path (used to check importability)."""


CLASS_TO_SLUG: Final[dict[str, str]] = {
    p.chat_class: p.slug for p in _PROVIDER_LIST if p.chat_class
}
"""LangChain chat-class name (e.g. ``ChatOpenAI``) → canonical slug, for ``describe_llm``."""


# ── Wizard "extra rows" — providers not in LangChain's _BUILTIN_PROVIDERS yet. ───
# Derived from registry: any provider whose canonical slug is not a known LangChain
# registry slug *and* whose wizard_aliases contain only its own slug.
def wizard_extra_rows(known_lc_slugs: set[str]) -> list[tuple[str, str, str, str]]:
    """Rows the wizard should add on top of LangChain's ``_BUILTIN_PROVIDERS``.

    Returns ``(slug, pip_pkg, chat_class, label)`` tuples for canonical slugs whose wizard alias
    is not registered in LangChain's chat-models index. Used to surface providers we ship via
    ``[project.optional-dependencies]`` that LangChain has not yet indexed (e.g. cerebras).
    """
    out: list[tuple[str, str, str, str]] = []
    for p in _PROVIDER_LIST:
        if not p.chat_class or not p.pip_extra:
            continue
        # Add a row only if none of its aliases are already in LangChain's registry.
        if any(a in known_lc_slugs for a in p.aliases):
            continue
        # Convert pip-extra (e.g. "openrouter") to PyPI dist name (langchain-openrouter).
        pip_dist = f"langchain-{p.pip_extra}" if not p.pip_extra.startswith("langchain") else p.pip_extra
        out.append((p.slug, pip_dist, p.chat_class, p.label))
    return out


__all__ = [
    "CLASS_TO_SLUG",
    "PROVIDERS",
    "provider_catalog",
    "PROVIDER_ENV_KEYS",
    "ProviderInfo",
    "SLUG_TO_CHAT_MODULE",
    "SLUG_TO_PIP_EXTRA",
    "WIZARD_DEFAULT_MODELS",
    "WIZARD_ENV_KEYS",
    "cli_auto_detect_rows",
    "wizard_extra_rows",
]


# Suppress the unused ``field`` import lint until/if any provider grows a default-factory list.
_ = field
