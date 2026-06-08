"""Bounded YAML loading for runtime MCP / project config paths."""

from __future__ import annotations

from typing import Any

import yaml

_MAX_DEPTH = 24


def _depth_of(obj: Any, *, depth: int = 0) -> int:
    if depth > _MAX_DEPTH:
        raise ValueError(f"YAML nesting exceeds {_MAX_DEPTH} levels")
    if isinstance(obj, dict):
        for v in obj.values():
            _depth_of(v, depth=depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _depth_of(v, depth=depth + 1)
    return depth


def safe_yaml_load(text: str, *, label: str = "yaml") -> Any:
    """Parse *text* with ``safe_load``, reject anchors/aliases, and cap nesting depth."""
    if "&" in text or "*" in text:
        raise ValueError(f"{label}: YAML anchors and aliases are not allowed")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"{label}: {exc}") from exc
    if data is not None:
        _depth_of(data)
    return data


__all__ = ["safe_yaml_load"]
