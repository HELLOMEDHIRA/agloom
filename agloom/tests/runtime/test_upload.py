"""Tests for staged file uploads (command.attach.file)."""

from __future__ import annotations

from agloom.runtime.upload import stage_attached_bytes


def test_stage_attached_bytes_writes_under_dot_agloom_uploads(tmp_path):
    class Agent:
        def __init__(self, root) -> None:
            self.config = {"cli_tools": {"working_dir": str(root)}}

    rel, n = stage_attached_bytes(Agent(tmp_path), filename="hello.txt", raw=b"abc")
    assert n == 3
    assert ".agloom_uploads" in rel
    assert "hello.txt" in rel
    assert (tmp_path / rel).read_bytes() == b"abc"


def test_stage_attached_bytes_rejects_oversized(tmp_path):
    class Agent:
        def __init__(self, root) -> None:
            self.config = {"cli_tools": {"working_dir": str(root)}}

    huge = b"x" * (9 * 1024 * 1024)
    try:
        stage_attached_bytes(Agent(tmp_path), filename="big.bin", raw=huge, max_bytes=1024)
    except ValueError as exc:
        assert "limit" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
