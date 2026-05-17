"""Unit tests for ``agloom.eval.runner`` (CLI eval harness; mocked LLM)."""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agloom.eval.runner import run_eval_cli


def _eval_args(path: Path, **overrides: object) -> argparse.Namespace:
    base = {
        "eval_file": str(path),
        "eval_seed": None,
        "eval_keep_going": False,
        "api_key_env": None,
        "model": None,
        "provider": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_run_eval_cli_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "absent.yaml"
    code = run_eval_cli(_eval_args(missing))
    assert code == 2


def test_run_eval_cli_empty_cases(tmp_path: Path) -> None:
    p = tmp_path / "e.yaml"
    p.write_text("cases: []\n", encoding="utf-8")
    assert run_eval_cli(_eval_args(p)) == 2


def test_run_eval_cli_no_llm(tmp_path: Path) -> None:
    p = tmp_path / "e.yaml"
    p.write_text(
        "cases:\n  - id: a\n    prompt: hello\n",
        encoding="utf-8",
    )
    with patch("agloom.eval.runner.resolve_llm_for_serve", return_value=None):
        assert run_eval_cli(_eval_args(p)) == 1


def test_run_eval_cli_seed_calls_random_seed(tmp_path: Path) -> None:
    p = tmp_path / "e.yaml"
    p.write_text(
        "cases:\n  - id: a\n    prompt: x\n",
        encoding="utf-8",
    )
    agent = MagicMock()
    agent.ainvoke = AsyncMock(return_value=MagicMock(output="ok"))
    agent.aclose = AsyncMock()

    async def _fake_create(*_a: object, **_kw: object):
        return agent

    with patch("agloom.eval.runner.resolve_llm_for_serve", return_value=object()):
        with patch("agloom.eval.runner.create_agent", side_effect=_fake_create):
            with patch.object(random, "seed") as seed_mock:
                code = run_eval_cli(_eval_args(p, eval_seed=424242))
                assert code == 0
                seed_mock.assert_called_once_with(424242)


def test_run_eval_cli_keep_going_runs_second_case_after_failure(tmp_path: Path) -> None:
    p = tmp_path / "e.yaml"
    p.write_text(
        "cases:\n"
        "  - id: bad\n"
        "    prompt: first\n"
        "    expect_substring: missing\n"
        "  - id: ok\n"
        "    prompt: second\n",
        encoding="utf-8",
    )
    agent = MagicMock()

    async def _ainvoke(prompt: str):
        return MagicMock(output=prompt)

    agent.ainvoke = AsyncMock(side_effect=_ainvoke)
    agent.aclose = AsyncMock()

    async def _fake_create(*_a: object, **_kw: object):
        return agent

    with patch("agloom.eval.runner.resolve_llm_for_serve", return_value=object()):
        with patch("agloom.eval.runner.create_agent", side_effect=_fake_create):
            code = run_eval_cli(_eval_args(p, eval_keep_going=True))
    assert code == 1
    assert agent.ainvoke.await_count == 2
