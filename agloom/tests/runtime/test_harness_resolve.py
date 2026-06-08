"""Harness enablement from CLI args and env."""

from __future__ import annotations

from argparse import Namespace

import pytest

from agloom.runtime.serve_cli import resolve_use_harness


@pytest.mark.parametrize(
    ("env", "no_harness", "expected"),
    [
        ({}, False, True),
        ({}, True, False),
        ({"AGLOOM_HARNESS": "0"}, False, False),
        ({"AGLOOM_HARNESS_ENABLED": "false"}, False, False),
        ({"AGLOOM_HARNESS": "1"}, True, True),
        ({"AGLOOM_HARNESS_ENABLED": "yes"}, True, True),
    ],
)
def test_resolve_use_harness_env_and_flag(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    no_harness: bool,
    expected: bool,
) -> None:
    for key in ("AGLOOM_HARNESS", "AGLOOM_HARNESS_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    args = Namespace(no_harness=no_harness)
    assert resolve_use_harness(args, lg_store=object()) is expected


def test_resolve_use_harness_off_without_store() -> None:
    args = Namespace(no_harness=False)
    assert resolve_use_harness(args, lg_store=None) is False
