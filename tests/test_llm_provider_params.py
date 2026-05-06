"""Unit tests for per-provider ``ai.llm`` kwarg filtering."""

from __future__ import annotations

from agloom_cli.llm_provider_params import normalize_provider_slug, spread_llm_options_for_provider
from agloom_cli.model_resolver import _slug_for_spread_llm


def test_spread_groq_drops_openai_only_penalties() -> None:
    out = spread_llm_options_for_provider(
        "groq",
        {"temperature": 0.1, "frequency_penalty": 0.5, "max_tokens": 100},
    )
    assert out["temperature"] == 0.1
    assert out["max_tokens"] == 100
    assert "frequency_penalty" not in out


def test_spread_openai_maps_timeout_and_max_completion() -> None:
    out = spread_llm_options_for_provider(
        "openai",
        {"timeout": 30, "temperature": 0, "max_completion_tokens": 500},
    )
    assert out["request_timeout"] == 30
    assert out["max_tokens"] == 500
    assert "timeout" not in out
    assert "max_completion_tokens" not in out


def test_spread_anthropic_stop_and_timeout_aliases() -> None:
    out = spread_llm_options_for_provider(
        "anthropic",
        {"stop": "</s>", "max_tokens": 50, "timeout": 60.0},
    )
    assert out["stop_sequences"] == ["</s>"]
    assert out["max_tokens"] == 50
    assert out["default_request_timeout"] == 60.0


def test_spread_ollama_num_predict_alias() -> None:
    out = spread_llm_options_for_provider("ollama", {"max_tokens": 128, "temperature": 0})
    assert out["num_predict"] == 128
    assert out["temperature"] == 0


def test_spread_google_max_output_alias() -> None:
    out = spread_llm_options_for_provider("google", {"max_tokens": 100, "top_p": 0.9})
    assert out["max_output_tokens"] == 100
    assert out["top_p"] == 0.9


def test_spread_mistral_seed_alias() -> None:
    out = spread_llm_options_for_provider("mistralai", {"seed": 42, "temperature": 0})
    assert out["random_seed"] == 42


def test_spread_nvidia_max_completion_alias() -> None:
    out = spread_llm_options_for_provider("nvidia", {"max_completion_tokens": 200, "top_p": 0.95})
    assert out["max_tokens"] == 200


def test_spread_litellm_maps_timeout() -> None:
    out = spread_llm_options_for_provider("litellm", {"timeout": 45, "max_tokens": 10})
    assert out["request_timeout"] == 45
    assert "timeout" not in out


def test_slug_for_spread_llm_openai_prefixed_model() -> None:
    assert _slug_for_spread_llm(model_provider=None, model="openai:gpt-4o-mini") == "openai"


def test_slug_for_spread_llm_respects_model_provider() -> None:
    assert _slug_for_spread_llm(model_provider="cohere", model="command-r") == "cohere"


def test_slug_for_spread_llm_unqualified_model_is_generic() -> None:
    assert _slug_for_spread_llm(model_provider=None, model="gpt-4o") == "__generic_init__"


def test_normalize_bedrock_and_vertex_aliases() -> None:
    assert normalize_provider_slug("bedrock_converse") == "bedrock"
    assert normalize_provider_slug("anthropic_bedrock") == "bedrock"
    assert normalize_provider_slug("vertex_ai") == "google_vertexai"
    assert normalize_provider_slug("watsonx") == "ibm"


def test_spread_cohere_timeout_alias() -> None:
    out = spread_llm_options_for_provider("cohere", {"timeout": 12, "temperature": 0})
    assert out["timeout_seconds"] == 12
    assert out["temperature"] == 0


def test_spread_bedrock_stop_and_completion_alias() -> None:
    out = spread_llm_options_for_provider(
        "bedrock_converse",
        {"stop": "|", "max_completion_tokens": 99, "temperature": 0.2},
    )
    assert out["stop_sequences"] == ["|"]
    assert out["max_tokens"] == 99
    assert out["temperature"] == 0.2


def test_spread_google_vertexai_max_output_alias() -> None:
    out = spread_llm_options_for_provider("google_vertexai", {"max_tokens": 200, "top_k": 40})
    assert out["max_output_tokens"] == 200
    assert out["top_k"] == 40


def test_spread_google_anthropic_vertex_aliases() -> None:
    out = spread_llm_options_for_provider(
        "google_anthropic_vertex",
        {"max_tokens": 50, "stop": "STOP"},
    )
    assert out["max_output_tokens"] == 50
    assert out["stop_sequences"] == ["STOP"]


def test_spread_azure_ai_request_timeout_alias() -> None:
    out = spread_llm_options_for_provider("azure_ai", {"timeout": 20, "temperature": 0.1})
    assert out["request_timeout"] == 20
    assert out["temperature"] == 0.1


def test_spread_fireworks_request_timeout_alias() -> None:
    out = spread_llm_options_for_provider("fireworks", {"timeout": 30, "max_tokens": 10})
    assert out["request_timeout"] == 30
