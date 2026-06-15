"""
agloom.llm — LLM provider resolution and routing.

Public API::

    from agloom.llm import get_model, try_resolve_llm_from_api_keys, describe_llm

The model resolver supports all LangChain provider integrations via
explicit ``provider:model_id`` syntax or automatic API-key detection.

Qwen3/vLLM chat-template compatibility for tool-bearing agents lives in
``agloom.llm.qwen_compat`` (used internally by REACT middleware).
"""

from .model_resolver import (
    MissingProviderApiKey,
    MissingProviderDependency,
    describe_llm,
    get_model,
    split_provider_prefix,
    try_resolve_llm_from_api_keys,
)

__all__ = [
    "get_model",
    "try_resolve_llm_from_api_keys",
    "describe_llm",
    "split_provider_prefix",
    "MissingProviderDependency",
    "MissingProviderApiKey",
]
