"""Bounded YAML loading."""

from __future__ import annotations

import pytest

from agloom.runtime.yaml_safe import safe_yaml_load


def test_safe_yaml_load_parses_mapping() -> None:
    data = safe_yaml_load("name: demo\nservers:\n  - a\n")
    assert data["name"] == "demo"


def test_safe_yaml_load_rejects_aliases() -> None:
    with pytest.raises(ValueError, match="aliases"):
        safe_yaml_load("anchor: &a\nref: *a\n")
