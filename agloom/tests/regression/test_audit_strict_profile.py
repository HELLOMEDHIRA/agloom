"""Platform embedded profile strict execution defaults."""

from agloom.profiles import resolve_profile_kwargs


def _reflection_blocked(agent: dict, config: dict | None) -> bool:
    return bool(agent.get("strict_execution") or (config or {}).get("strict_execution"))


def test_platform_embedded_disables_recovery_paths():
    kw = resolve_profile_kwargs("platform_embedded")
    agent = {"strict_execution": kw["strict_execution"]}
    assert kw["strict_execution"] is True
    assert _reflection_blocked(agent, {}) is True


def test_interactive_allows_reflection_recovery():
    kw = resolve_profile_kwargs("interactive")
    agent = {"strict_execution": kw["strict_execution"]}
    assert kw["strict_execution"] is False
    assert _reflection_blocked(agent, {}) is False
