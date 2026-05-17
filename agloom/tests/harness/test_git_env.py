"""GitSession subprocess environment hardening."""

from __future__ import annotations

import os

from agloom.harness.git import GitSession


def test_git_env_strips_redirect_vars(monkeypatch) -> None:
    monkeypatch.setenv("GIT_DIR", "/tmp/evil")
    monkeypatch.setenv("GIT_WORK_TREE", "/tmp/evil")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-should-not-appear")
    gs = GitSession(cwd=".")
    env = gs._git_env({"EXTRA": "1"})
    assert "GIT_DIR" not in env
    assert "GIT_WORK_TREE" not in env
    assert env.get("EXTRA") == "1"
    assert env.get("GIT_AUTHOR_NAME") == "agent"
    assert "OPENAI_API_KEY" not in env
