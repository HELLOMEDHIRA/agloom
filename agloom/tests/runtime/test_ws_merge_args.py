"""WebSocket query-string overrides for per-connection agent configuration."""

from __future__ import annotations

from argparse import Namespace

from agloom.runtime.serve_cli import merge_ws_connection_args


def test_merge_ws_query_overrides_model_and_sampling() -> None:
    base = Namespace(
        model="openai:gpt-4o-mini",
        provider=None,
        temperature=0.5,
        top_p=None,
        top_k=None,
        pattern=None,
        session_max_turns=50,
    )
    out = merge_ws_connection_args(base, "/?model=groq:llama-3.1-8b&temperature=0.1&top_p=0.9&top_k=40")
    assert out.model == "groq:llama-3.1-8b"
    assert out.temperature == 0.1
    assert out.top_p == 0.9
    assert out.top_k == 40


def test_merge_ws_empty_path_returns_copy() -> None:
    base = Namespace(model="x")
    out = merge_ws_connection_args(base, "")
    assert out.model == "x"
    assert out is not base
