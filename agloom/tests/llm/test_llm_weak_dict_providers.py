"""Provider chat models must not crash LLM-keyed caches (unhashable Pydantic chat classes)."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from agloom.llm.provider_registry import PROVIDERS
from agloom.llm_utils import exercise_llm_weak_dict_paths, llm_weak_dict_key_ok

pytestmark = pytest.mark.provider_probe

# Slugs that need cloud IAM / multi-field auth — skip live construction in CI.
_SKIP_PROBE_SLUGS = frozenset(
    {
        "bedrock",
        "google_vertexai",
        "google_anthropic_vertex",
        "snowflake",
        "azure_ai",
        "ibm",
        "huggingface",
        "baseten",
    }
)

# Extra kwargs beyond model + temperature for picky constructors.
_PROBE_EXTRA: dict[str, dict[str, Any]] = {
    "ollama": {"base_url": "http://127.0.0.1:11434"},
    "vllm": {"base_url": "http://127.0.0.1:8000/v1", "api_key": "EMPTY"},
    "openrouter": {"openai_api_key": "probe-key"},
    "azure_openai": {
        "api_key": "probe-key",
        "azure_endpoint": "https://example.openai.azure.com",
        "api_version": "2024-02-01",
    },
}


def _probe_providers() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for slug, info in PROVIDERS.items():
        if slug in _SKIP_PROBE_SLUGS:
            continue
        if not info.chat_module or not info.chat_class:
            continue
        rows.append((slug, info.chat_module, info.chat_class))
    return sorted(rows, key=lambda r: r[0])


def _construct_chat(slug: str, module: str, class_name: str) -> Any | None:
    try:
        mod = importlib.import_module(module)
        cls = getattr(mod, class_name)
    except (ImportError, AttributeError):
        return None

    base: dict[str, Any] = {
        "model": PROVIDERS[slug].default_model,
        "temperature": 0,
    }
    if slug not in ("ollama",):
        base["api_key"] = "probe-key-not-real"
    base.update(_PROBE_EXTRA.get(slug, {}))

    # LangChain OpenAI-shaped clients often accept openai_api_key instead of api_key.
    if slug in ("openai", "vllm", "litellm", "deepseek", "fireworks", "together", "perplexity"):
        base.setdefault("openai_api_key", base.pop("api_key", "probe-key"))

    try:
        return cls(**base)
    except TypeError:
        try:
            return cls(model=PROVIDERS[slug].default_model)
        except Exception:
            return None
    except Exception:
        return None


@pytest.mark.parametrize(("slug", "module", "class_name"), _probe_providers())
def test_provider_chat_models_exercise_llm_caches_without_error(
    slug: str,
    module: str,
    class_name: str,
) -> None:
    llm = _construct_chat(slug, module, class_name)
    if llm is None:
        pytest.skip(f"{slug}: optional dep {module}.{class_name} not installed or ctor failed")

    exercise_llm_weak_dict_paths(llm)

    # Document hashability for maintainers (id fallback is always safe).
    hashable = llm_weak_dict_key_ok(llm)
    if not hashable:
        pytest.xfail(
            f"{slug} ({class_name}): weakref ok but not hashable — uses id(llm) cache fallback",
        )
