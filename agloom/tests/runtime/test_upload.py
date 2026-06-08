"""Tests for staged file uploads (command.attach.file)."""

from __future__ import annotations

import sys

import pytest

from agloom.runtime.upload import release_upload_quota, stage_attached_bytes


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


def test_stage_attached_bytes_sanitizes_traversal_filename(tmp_path):
    class Agent:
        def __init__(self, root) -> None:
            self.config = {"cli_tools": {"working_dir": str(root)}}

    rel, _ = stage_attached_bytes(Agent(tmp_path), filename="../../etc/passwd", raw=b"x")
    assert ".." not in rel
    assert rel.startswith(".agloom_uploads/")
    assert rel.endswith("_passwd")
    assert (tmp_path / rel).resolve().is_relative_to(tmp_path.resolve())


@pytest.mark.skipif(sys.platform == "win32", reason="symlink escape test is Unix-oriented")
def test_stage_attached_bytes_rejects_symlink_upload_dir(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    upload_link = root / ".agloom_uploads"
    upload_link.symlink_to(outside, target_is_directory=True)

    class Agent:
        def __init__(self, r) -> None:
            self.config = {"cli_tools": {"working_dir": str(r)}}

    with pytest.raises(ValueError, match="escapes working directory"):
        stage_attached_bytes(Agent(root), filename="x.txt", raw=b"1")
    assert not any(outside.iterdir())


def test_release_upload_quota_decrements(tmp_path):
    class Agent:
        def __init__(self, root) -> None:
            self.config = {"cli_tools": {"working_dir": str(root)}}

    agent = Agent(tmp_path)
    _, n = stage_attached_bytes(agent, filename="a.txt", raw=b"abc")
    release_upload_quota(agent, n)
    _, n2 = stage_attached_bytes(agent, filename="b.txt", raw=b"xyz")
    assert n2 == 3
