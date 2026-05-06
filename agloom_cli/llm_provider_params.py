"""Provider-specific ``ai.llm`` kwargs for LangChain chat models.

Each integration exposes different constructor fields (see LangChain reference docs, e.g.
https://reference.langchain.com/python/ ). We normalize YAML-friendly names (``stop``,
``max_tokens``, ``timeout``) into the parameter names each class expects, then drop keys the
provider does not support so optional extras are not forced to accept a one-size-fits-all dict.
"""

from __future__ import annotations

from typing import Any, Mapping

# Tuning / request fields allowed per provider (from ``langchain-*`` model_fields; excludes
# credentials, clients, callbacks, etc.).
#
# Reference index: https://docs.langchain.com/oss/python/integrations/chat

# Amazon Bedrock (``langchain_aws`` — ``ChatBedrock`` / ``ChatBedrockConverse`` tuning overlap).
_BEDROCK_LLM_KEYS: frozenset[str] = frozenset(
    {
        "temperature",
        "max_tokens",
        "top_p",
        "stop_sequences",
        "timeout",
        "max_retries",
        "model_kwargs",
        "additional_model_request_fields",
        "additional_model_response_field_paths",
        "output_config",
        "performance_config",
        "service_tier",
        "system",
        "guardrail_config",
        "guard_last_turn_only",
        "request_metadata",
        "raw_blocks",
    }
)

_OPENAI_FAMILY_LLM_KEYS: frozenset[str] = frozenset(
    {
        "temperature",
        "max_tokens",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "stop",
        "n",
        "logprobs",
        "top_logprobs",
        "logit_bias",
        "reasoning_effort",
        "reasoning",
        "verbosity",
        "request_timeout",
        "max_retries",
        "stream_chunk_timeout",
        "model_kwargs",
        "extra_body",
        "context_management",
        "include",
        "service_tier",
        "store",
        "truncation",
        "use_previous_response_id",
        "use_responses_api",
    }
)

LLM_PARAM_KEYS_BY_PROVIDER: dict[str, frozenset[str]] = {
    # langchain_openai.ChatOpenAI
    "openai": _OPENAI_FAMILY_LLM_KEYS,
    # Local OpenAI-compatible HTTP (vLLM, etc.) — same client.
    "vllm": _OPENAI_FAMILY_LLM_KEYS,
    # langchain_anthropic.ChatAnthropic
    "anthropic": frozenset(
        {
            "max_tokens",
            "temperature",
            "top_k",
            "top_p",
            "default_request_timeout",
            "max_retries",
            "stop_sequences",
            "model_kwargs",
            "thinking",
            "output_config",
            "effort",
        }
    ),
    # langchain_google_genai.ChatGoogleGenerativeAI
    "google": frozenset(
        {
            "temperature",
            "top_p",
            "top_k",
            "max_output_tokens",
            "n",
            "max_retries",
            "timeout",
            "model_kwargs",
            "stop",
            "seed",
            "thinking_budget",
            "include_thoughts",
            "safety_settings",
            "response_mime_type",
            "response_schema",
            "thinking_level",
            "cached_content",
            "media_resolution",
            "image_config",
            "response_modalities",
            "labels",
        }
    ),
    # langchain_groq.ChatGroq
    "groq": frozenset(
        {
            "temperature",
            "stop",
            "reasoning_format",
            "reasoning_effort",
            "model_kwargs",
            "request_timeout",
            "max_retries",
            "n",
            "max_tokens",
            "service_tier",
            "default_headers",
            "default_query",
        }
    ),
    # langchain_ollama.ChatOllama
    "ollama": frozenset(
        {
            "reasoning",
            "mirostat",
            "mirostat_eta",
            "mirostat_tau",
            "num_ctx",
            "num_gpu",
            "num_thread",
            "num_predict",
            "repeat_last_n",
            "repeat_penalty",
            "temperature",
            "seed",
            "logprobs",
            "top_logprobs",
            "stop",
            "tfs_z",
            "top_k",
            "top_p",
            "format",
            "keep_alive",
        }
    ),
    # langchain_litellm.ChatLiteLLM
    "litellm": frozenset(
        {
            "temperature",
            "model_kwargs",
            "top_p",
            "top_k",
            "n",
            "max_tokens",
            "num_ctx",
            "max_retries",
            "request_timeout",
            "extra_headers",
        }
    ),
    # langchain_mistralai.ChatMistralAI
    "mistralai": frozenset(
        {
            "temperature",
            "max_tokens",
            "top_p",
            "random_seed",
            "safe_mode",
            "model_kwargs",
            "timeout",
            "max_retries",
        }
    ),
    # langchain_xai.ChatXAI — OpenAI-shaped + xAI extras.
    "xai": _OPENAI_FAMILY_LLM_KEYS | frozenset({"search_parameters"}),
    # langchain_cerebras.ChatCerebras
    "cerebras": _OPENAI_FAMILY_LLM_KEYS | frozenset({"disable_reasoning"}),
    # langchain_nvidia_ai_endpoints.ChatNVIDIA
    "nvidia": frozenset(
        {
            "temperature",
            "max_tokens",
            "top_p",
            "seed",
            "stop",
            "stream_options",
            "default_headers",
            "model_kwargs",
        }
    ),
    # OpenRouter uses an OpenAI-compatible API in practice.
    "openrouter": _OPENAI_FAMILY_LLM_KEYS,
    # langchain_cohere.ChatCohere
    "cohere": frozenset(
        {
            "temperature",
            "stop",
            "timeout_seconds",
            "preamble",
            "base_url",
        }
    ),
    # langchain_aws (Bedrock). Slugs: ``bedrock``, ``bedrock_converse``, ``anthropic_bedrock``.
    "bedrock": _BEDROCK_LLM_KEYS,
    # langchain_azure_ai — OpenAI-shaped Azure AI chat completions.
    "azure_ai": _OPENAI_FAMILY_LLM_KEYS | frozenset({"project_endpoint"}),
    # langchain_deepseek.ChatDeepSeek
    "deepseek": _OPENAI_FAMILY_LLM_KEYS,
    # langchain_fireworks.ChatFireworks
    "fireworks": frozenset(
        {
            "temperature",
            "max_tokens",
            "n",
            "stop",
            "request_timeout",
            "max_retries",
            "model_kwargs",
            "service_tier",
            "stream_usage",
        }
    ),
    # langchain_ibm.ChatWatsonx
    "ibm": frozenset(
        {
            "temperature",
            "max_tokens",
            "max_completion_tokens",
            "top_p",
            "stop",
            "seed",
            "frequency_penalty",
            "presence_penalty",
            "logprobs",
            "top_logprobs",
            "logit_bias",
            "reasoning_effort",
            "repetition_penalty",
            "length_penalty",
            "n",
            "response_format",
            "include_reasoning",
            "chat_template_kwargs",
            "model_kwargs",
        }
    ),
    # langchain_perplexity.ChatPerplexity
    "perplexity": frozenset(
        {
            "temperature",
            "max_tokens",
            "request_timeout",
            "max_retries",
            "model_kwargs",
            "reasoning_effort",
            "disable_search",
            "enable_search_classifier",
            "language_preference",
            "last_updated_after_filter",
            "last_updated_before_filter",
            "media_response",
            "return_images",
            "return_related_questions",
            "search_after_date_filter",
            "search_before_date_filter",
            "search_domain_filter",
            "search_mode",
            "search_recency_filter",
            "web_search_options",
        }
    ),
    # langchain_sambanova.ChatSambaNovaCloud — legacy class without ``model_fields``; stay OpenAI-like.
    "sambanova": _OPENAI_FAMILY_LLM_KEYS,
    # langchain_together.ChatTogether
    "together": _OPENAI_FAMILY_LLM_KEYS,
    # langchain_upstage.ChatUpstage
    "upstage": _OPENAI_FAMILY_LLM_KEYS
    | frozenset(
        {
            "top_k",
            "tokenizer_name",
            "prompt_cache_key",
        }
    ),
    # langchain_google_vertexai.ChatVertexAI
    "google_vertexai": frozenset(
        {
            "temperature",
            "top_p",
            "top_k",
            "max_output_tokens",
            "n",
            "max_retries",
            "timeout",
            "model_kwargs",
            "stop",
            "seed",
            "frequency_penalty",
            "presence_penalty",
            "thinking_budget",
            "include_thoughts",
            "safety_settings",
            "response_mime_type",
            "response_schema",
            "labels",
            "logprobs",
            "response_modalities",
            "cached_content",
            "additional_headers",
            "audio_timestamp",
        }
    ),
    # Anthropic models on Vertex — parameter surface spans both Anthropic + Vertex conventions.
    "google_anthropic_vertex": frozenset(
        {
            "max_tokens",
            "max_output_tokens",
            "temperature",
            "top_k",
            "top_p",
            "default_request_timeout",
            "max_retries",
            "stop_sequences",
            "timeout",
            "model_kwargs",
            "thinking",
            "output_config",
            "effort",
            "frequency_penalty",
            "presence_penalty",
            "seed",
            "stop",
            "n",
            "logprobs",
            "safety_settings",
            "labels",
        }
    ),
    # ``init_chat_model`` / long-tail slugs: only pass widely recognized knobs; put the rest in
    # ``model_kwargs`` in YAML if needed.
    "__generic_init__": frozenset(
        {
            "temperature",
            "max_tokens",
            "top_p",
            "top_k",
            "stop",
            "max_retries",
            "timeout",
            "model_kwargs",
            "seed",
            "n",
            "frequency_penalty",
            "presence_penalty",
            "reasoning_effort",
        }
    ),
}


def normalize_provider_slug(slug: str) -> str:
    s = slug.strip().lower().replace("-", "_")
    if s in ("mistral",):
        return "mistralai"
    if s in ("google", "gemini"):
        return "google"
    if s in ("vertexai", "vertex_ai"):
        return "google_vertexai"
    if s in ("bedrock_converse", "anthropic_bedrock"):
        return "bedrock"
    if s == "watsonx":
        return "ibm"
    return s


def _coerce_stop_sequences(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return [str(value)]


def _apply_yaml_aliases(provider: str, d: dict[str, Any]) -> None:
    """Map shared YAML names onto provider-specific fields (in place)."""
    # OpenAI-shaped clients use request_timeout, not timeout.
    if provider in (
        "openai",
        "vllm",
        "xai",
        "cerebras",
        "groq",
        "openrouter",
        "azure_ai",
        "deepseek",
        "together",
        "upstage",
    ):
        if d.get("request_timeout") is None and d.get("timeout") is not None:
            d["request_timeout"] = d.pop("timeout")
    if provider == "anthropic":
        if d.get("default_request_timeout") is None and d.get("timeout") is not None:
            d["default_request_timeout"] = d.pop("timeout")
        elif "timeout" in d:
            d.pop("timeout", None)
        if d.get("stop_sequences") is None and d.get("stop") is not None:
            seq = _coerce_stop_sequences(d.pop("stop"))
            if seq is not None:
                d["stop_sequences"] = seq
        elif "stop" in d:
            d.pop("stop", None)

    if provider == "litellm":
        if d.get("request_timeout") is None and d.get("timeout") is not None:
            d["request_timeout"] = d.pop("timeout")
        elif "timeout" in d:
            d.pop("timeout", None)

    if provider in ("fireworks", "perplexity"):
        if d.get("request_timeout") is None and d.get("timeout") is not None:
            d["request_timeout"] = d.pop("timeout")
        elif "timeout" in d:
            d.pop("timeout", None)

    if provider == "cohere":
        if d.get("timeout_seconds") is None and d.get("timeout") is not None:
            d["timeout_seconds"] = d.pop("timeout")
        elif "timeout" in d:
            d.pop("timeout", None)

    if provider == "bedrock":
        if d.get("max_tokens") is None and d.get("max_completion_tokens") is not None:
            d["max_tokens"] = d.pop("max_completion_tokens")
        elif "max_completion_tokens" in d:
            d.pop("max_completion_tokens", None)
        if d.get("stop_sequences") is None and d.get("stop") is not None:
            seq = _coerce_stop_sequences(d.pop("stop"))
            if seq is not None:
                d["stop_sequences"] = seq
        elif "stop" in d:
            d.pop("stop", None)

    if provider == "google_vertexai":
        if d.get("max_output_tokens") is None and d.get("max_tokens") is not None:
            d["max_output_tokens"] = d.pop("max_tokens")
        elif "max_tokens" in d:
            d.pop("max_tokens", None)
        if d.get("max_output_tokens") is None and d.get("max_completion_tokens") is not None:
            d["max_output_tokens"] = d.pop("max_completion_tokens")
        elif "max_completion_tokens" in d:
            d.pop("max_completion_tokens", None)

    if provider == "google_anthropic_vertex":
        if d.get("max_output_tokens") is None and d.get("max_tokens") is not None:
            d["max_output_tokens"] = d.pop("max_tokens")
        elif "max_tokens" in d:
            d.pop("max_tokens", None)
        if d.get("max_output_tokens") is None and d.get("max_completion_tokens") is not None:
            d["max_output_tokens"] = d.pop("max_completion_tokens")
        elif "max_completion_tokens" in d:
            d.pop("max_completion_tokens", None)
        if d.get("stop_sequences") is None and d.get("stop") is not None:
            seq = _coerce_stop_sequences(d.pop("stop"))
            if seq is not None:
                d["stop_sequences"] = seq
        elif "stop" in d:
            d.pop("stop", None)

    # Token limit field names
    if provider in ("openai", "vllm", "xai", "cerebras", "groq", "openrouter", "nvidia"):
        if d.get("max_tokens") is None and d.get("max_completion_tokens") is not None:
            d["max_tokens"] = d.pop("max_completion_tokens")
        elif "max_completion_tokens" in d:
            d.pop("max_completion_tokens", None)

    if provider == "google":
        if d.get("max_output_tokens") is None and d.get("max_tokens") is not None:
            d["max_output_tokens"] = d.pop("max_tokens")
        elif "max_tokens" in d:
            d.pop("max_tokens", None)
        if d.get("max_output_tokens") is None and d.get("max_completion_tokens") is not None:
            d["max_output_tokens"] = d.pop("max_completion_tokens")
        elif "max_completion_tokens" in d:
            d.pop("max_completion_tokens", None)

    if provider == "ollama":
        if d.get("num_predict") is None and d.get("max_tokens") is not None:
            d["num_predict"] = d.pop("max_tokens")
        elif "max_tokens" in d:
            d.pop("max_tokens", None)
        if d.get("num_predict") is None and d.get("max_completion_tokens") is not None:
            d["num_predict"] = d.pop("max_completion_tokens")
        elif "max_completion_tokens" in d:
            d.pop("max_completion_tokens", None)

    if provider == "mistralai":
        if d.get("random_seed") is None and d.get("seed") is not None:
            d["random_seed"] = d.pop("seed")
        elif "seed" in d:
            d.pop("seed", None)


def spread_llm_options_for_provider(provider_slug: str, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Return constructor kwargs derived from *kwargs* for *provider_slug*."""
    slug = normalize_provider_slug(provider_slug)
    allow = LLM_PARAM_KEYS_BY_PROVIDER.get(slug, LLM_PARAM_KEYS_BY_PROVIDER["__generic_init__"])
    merged: dict[str, Any] = dict(kwargs)
    _apply_yaml_aliases(slug, merged)
    return {k: merged[k] for k in allow if k in merged and merged[k] is not None}
