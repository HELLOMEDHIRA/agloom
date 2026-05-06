"""Central safety caps."""

from agloom_cli.safety_limits import HITL_DETAIL_HARD_CAP_CHARS, clamp_hitl_detail


def test_clamp_hitl_detail_noop_under_cap() -> None:
    assert clamp_hitl_detail("hello") == "hello"


def test_clamp_hitl_detail_over_cap() -> None:
    s = "x" * (HITL_DETAIL_HARD_CAP_CHARS + 50)
    out = clamp_hitl_detail(s)
    assert out.startswith("x" * HITL_DETAIL_HARD_CAP_CHARS)
    assert "pathological" in out.lower()
    assert len(out) == HITL_DETAIL_HARD_CAP_CHARS + len(
        "\n\n[agloom] Truncated: exceeded HITL_DETAIL_HARD_CAP_CHARS (pathological size guard)."
    )
