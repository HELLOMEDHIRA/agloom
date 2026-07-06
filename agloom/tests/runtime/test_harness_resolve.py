"""Harness enablement from CLI args only (no environment overrides)."""

from __future__ import annotations

from argparse import Namespace

import pytest

from agloom.runtime.serve_cli import resolve_use_harness


@pytest.mark.parametrize(
    ("no_harness", "expected"),
    [
        (False, True),
        (True, False),
    ],
)
def test_resolve_use_harness_flag_only(no_harness: bool, expected: bool) -> None:
    args = Namespace(no_harness=no_harness)
    assert resolve_use_harness(args, lg_store=object()) is expected


def test_resolve_use_harness_env_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGLOOM_HARNESS", "0")
    monkeypatch.setenv("AGLOOM_HARNESS_ENABLED", "false")
    args = Namespace(no_harness=False)
    assert resolve_use_harness(args, lg_store=object()) is True


def test_resolve_use_harness_off_without_store() -> None:
    args = Namespace(no_harness=False)
    assert resolve_use_harness(args, lg_store=None) is False
