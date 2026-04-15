"""Configuration file loading — yaml/toml support."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Optional

import tomli
import yaml


def load_config(path: Path) -> dict[str, Any]:
    """Load configuration from yaml or toml file.

    Supported formats:
    - .yaml / .yml → PyYAML
    - .toml → tomli

    Config precedence (highest):
    1. CLI flags
    2. Config file
    3. Environment variables
    4. Defaults
    """
    if not path.exists():
        return {}

    suffix = path.suffix.lower()

    with open(path, "rb" if suffix == ".toml" else "r") as f:
        if suffix == ".toml":
            return tomli.load(f)
        return yaml.safe_load(f) or {}


def get_thread_id(config: dict[str, Any]) -> str:
    """Get thread ID from config or generate new one.

    Priority:
    1. config.thread_id (if set)
    2. AGLOOM_THREAD_ID env var
    3. Generate new UUID
    """
    if config.get("thread_id"):
        return config["thread_id"]

    if os.environ.get("AGLOOM_THREAD_ID"):
        return os.environ["AGLOOM_THREAD_ID"]

    return uuid.uuid4().hex[:8]


def resolve_model(model_id: Optional[str]) -> Any:
    """Resolve model from ID or env var.

    Priority:
    1. Explicit model_id
    2. OPENAI_MODEL_ID
    3. ANTHROPIC_MODEL_ID
    4. GROQ_MODEL_ID
    5. Auto-detect from available env vars
    """
    from .model_resolver import get_model

    if model_id and model_id != "auto":
        return get_model(model_id)

    env_model = (
        os.environ.get("OPENAI_MODEL_ID") or os.environ.get("ANTHROPIC_MODEL_ID") or os.environ.get("GROQ_MODEL_ID")
    )

    if env_model:
        return get_model(env_model)

    if os.environ.get("OPENAI_API_KEY"):
        return get_model("gpt-4o")

    if os.environ.get("ANTHROPIC_API_KEY"):
        return get_model("claude-3-5-sonnet-20241022")

    if os.environ.get("GROQ_API_KEY"):
        return get_model("meta-llama/llama-4-scout-17b-16e-instruct")

    return None
