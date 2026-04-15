"""Model resolution — auto-detect available LLM providers."""

from __future__ import annotations

import os
from typing import Any


def get_model(model_id: str, **kwargs) -> Any:
    """Get a LangChain chat model by ID.

    Supports:
    - OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.
    - Anthropic: claude-3-5-sonnet-20241022, claude-3-opus, etc.
    - Groq: meta-llama/llama-4-scout-17b-16e-instruct, etc.
    - Ollama: llama3, mistral, etc.
    - HuggingFace: ...
    - NVIDIA NIM: ...

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

    if "groq" in model_id_lower or "/" in model_id:
        return _get_groq_model(model_id, **kwargs)

    if "llama" in model_id_lower or "mistral" in model_id_lower:
        if os.environ.get("OLLAMA_HOST"):
            return _get_ollama_model(model_id, **kwargs)
        return _get_groq_model(model_id, **kwargs)

    return _get_default_model(model_id, **kwargs)


def _get_openai_model(model_id: str, **kwargs) -> Any:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=os.environ.get("OPENAI_API_KEY"),
    )


def _get_anthropic_model(model_id: str, **kwargs) -> Any:
    from langchain_anthropic import ChatAnthropic

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


def _get_groq_model(model_id: str, **kwargs) -> Any:
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
        api_key=os.environ.get("GROQ_API_KEY"),
    )


def _get_ollama_model(model_id: str, **kwargs) -> Any:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=model_id,
        temperature=kwargs.get("temperature", 0),
    )


def _get_default_model(model_id: str, **kwargs) -> Any:
    if os.environ.get("OPENAI_API_KEY"):
        return _get_openai_model("gpt-4o", **kwargs)

    if os.environ.get("ANTHROPIC_API_KEY"):
        return _get_anthropic_model("claude-3-5-sonnet-20241022", **kwargs)

    if os.environ.get("GROQ_API_KEY"):
        return _get_groq_model("meta-llama/llama-4-scout-17b-16e-instruct", **kwargs)

    raise ValueError("No model found. Set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY")
