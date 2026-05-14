"""``resolve_llm_for_serve`` treats yaml placeholder ``auto`` like an unset model."""

from __future__ import annotations

import argparse
from unittest.mock import patch

from agloom.runtime.serve_cli import resolve_llm_for_serve


def test_resolve_llm_auto_delegates_to_env_autodetect() -> None:
    args = argparse.Namespace(
        model="auto",
        provider=None,
        temperature=None,
        top_p=None,
        top_k=None,
        max_tokens=None,
    )
    with patch("agloom.runtime.serve_cli.try_resolve_llm_from_api_keys", return_value=None) as tr:
        out = resolve_llm_for_serve(args)
        assert out is None
        tr.assert_called_once_with(interactive=False)


def test_resolve_llm_auto_case_insensitive() -> None:
    args = argparse.Namespace(
        model="auto",
        provider=None,
        temperature=None,
        top_p=None,
        top_k=None,
        max_tokens=None,
    )
    with patch("agloom.runtime.serve_cli.try_resolve_llm_from_api_keys", return_value="ok") as tr:
        assert resolve_llm_for_serve(args) == "ok"
        tr.assert_called_once()


def test_resolve_llm_explicit_still_calls_get_model() -> None:
    args = argparse.Namespace(
        model="groq:meta-llama/llama-3.3-70b-versatile",
        provider=None,
        temperature=None,
        top_p=None,
        top_k=None,
        max_tokens=None,
    )
    sentinel = object()
    with (
        patch("agloom.runtime.serve_cli.get_model", return_value=sentinel) as gm,
        patch("agloom.runtime.serve_cli.try_resolve_llm_from_api_keys") as tr,
    ):
        assert resolve_llm_for_serve(args) is sentinel
        gm.assert_called_once()
        tr.assert_not_called()
