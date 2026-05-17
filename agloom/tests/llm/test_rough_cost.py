"""Heuristic USD buckets in :mod:`agloom.llm.rough_cost` (meta vs groq for Llama ids)."""

from agloom.llm.rough_cost import estimate_llm_cost_usd


def test_estimate_llm_cost_usd_nvidia_slug_from_model() -> None:
    c = estimate_llm_cost_usd(
        model="nvidia:meta/llama-4-maverick-17b-128e-instruct",
        input_tokens=1,
        output_tokens=16,
    )
    assert c > 0.0
    assert c < 0.01


def test_estimate_zero_when_no_tokens() -> None:
    assert (
        estimate_llm_cost_usd(
            model="nvidia:x",
            input_tokens=0,
            output_tokens=0,
        )
        == 0.0
    )


def test_estimate_uses_default_slug_when_model_has_no_prefix() -> None:
    c = estimate_llm_cost_usd(model="some-bare-id", input_tokens=1000, output_tokens=500)
    assert c > 0.0


def test_bare_claude_model_bucket_matches_anthropic_rates() -> None:
    c_claude = estimate_llm_cost_usd(model="claude-3-5-sonnet-latest", input_tokens=1_000_000, output_tokens=0)
    c_generic = estimate_llm_cost_usd(model="some-bare-id", input_tokens=1_000_000, output_tokens=0)
    assert c_claude > c_generic


def test_bare_llama_uses_meta_bucket_not_groq() -> None:
    c_bare = estimate_llm_cost_usd(model="llama-3.1-8b-instant", input_tokens=1_000_000, output_tokens=0)
    c_groq = estimate_llm_cost_usd(model="groq:llama-3.1-8b-instant", input_tokens=1_000_000, output_tokens=0)
    assert c_bare > c_groq
