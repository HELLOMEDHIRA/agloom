"""Workload profiles — architect-managed execution presets for :func:`agloom.create_agent`."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class WorkloadProfile(StrEnum):
    """Execution tradeoffs only; context fidelity is always-on via Context Plane."""

    INTERACTIVE = "interactive"
    HARNESS_LONG = "harness_long"
    PLATFORM_EMBEDDED = "platform_embedded"
    BATCH_FROZEN = "batch_frozen"
    TOOL_AGENT = "tool_agent"


_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    WorkloadProfile.INTERACTIVE: {
        "strict_execution": False,
        "frozen": False,
        "enable_auto_escalation": False,
        "max_pattern_depth": 0,
    },
    WorkloadProfile.TOOL_AGENT: {
        "strict_execution": False,
        "frozen": False,
        "enable_auto_escalation": False,
        "max_pattern_depth": 0,
    },
    WorkloadProfile.HARNESS_LONG: {
        "strict_execution": True,
        "frozen": False,
        "harness": True,
        "enable_auto_escalation": False,
        "max_pattern_depth": 0,
        "react_recursion_limit": 100,
        "session_max_turns": 200,
    },
    WorkloadProfile.PLATFORM_EMBEDDED: {
        "strict_execution": True,
        "frozen": True,
        "harness": True,
        "enable_auto_escalation": False,
        "max_pattern_depth": 0,
        "react_recursion_limit": 100,
        "session_max_turns": 200,
        "llm_timeout": 300.0,
        "react_graph_timeout": 900.0,
    },
    WorkloadProfile.BATCH_FROZEN: {
        "strict_execution": True,
        "frozen": True,
        "enable_auto_escalation": False,
        "max_pattern_depth": 0,
        "enable_pattern_spawns": False,
    },
}


def normalize_profile_name(profile: str | WorkloadProfile | None) -> WorkloadProfile:
    if profile is None:
        return WorkloadProfile.INTERACTIVE
    if isinstance(profile, WorkloadProfile):
        return profile
    key = profile.strip().lower().replace("-", "_")
    try:
        return WorkloadProfile(key)
    except ValueError:
        valid = ", ".join(p.value for p in WorkloadProfile)
        raise ValueError(f"Unknown workload profile {profile!r}. Valid: {valid}") from None


def resolve_profile_kwargs(
    profile: str | WorkloadProfile | None,
    *,
    explicit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge profile defaults; explicit kwargs from caller win."""
    name = normalize_profile_name(profile)
    merged = dict(_PROFILE_DEFAULTS.get(name, {}))
    if explicit:
        merged.update({k: v for k, v in explicit.items() if v is not None})
    merged["workload_profile"] = name.value
    return merged
