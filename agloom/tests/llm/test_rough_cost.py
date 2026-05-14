"""Rough USD estimates for missing provider cost metadata."""

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
