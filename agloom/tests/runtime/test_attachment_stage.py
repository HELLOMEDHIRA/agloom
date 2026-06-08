"""Attachment staging path containment (``prepare_invoke_attachments``)."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from agloom.runtime.attachment_stage import prepare_invoke_attachments


def test_prepare_invoke_attachments_writes_under_working_dir(tmp_path: Path) -> None:
    wd = tmp_path / "w"
    wd.mkdir()
    raw = b"x"
    b64 = base64.b64encode(raw).decode("ascii")
    att = SimpleNamespace(name="note.txt", mime_type="text/plain", data_base64=b64)
    prompt, summaries = prepare_invoke_attachments(
        prompt="hi",
        attachments=[att],
        thread="t1",
        working_dir=wd,
        model_id="openai:gpt-4o-mini",
    )
    assert isinstance(prompt, str)
    assert "[Attached files are available in the workspace at:]" in prompt
    assert len(summaries) == 1
    assert summaries[0]["byte_length"] == 1
    rel = summaries[0]["path"]
    assert rel.startswith(".agloom/attachments/")
    assert "note.txt" in rel
    full = (wd / Path(rel)).resolve()
    assert full.is_file()
    assert full.read_bytes() == raw


def test_prepare_invoke_attachments_rejects_executable(tmp_path: Path) -> None:
    wd = tmp_path / "w"
    wd.mkdir()
    raw = b"MZ"
    b64 = base64.b64encode(raw).decode("ascii")
    att = SimpleNamespace(name="payload.exe", mime_type="application/octet-stream", data_base64=b64)
    try:
        prepare_invoke_attachments(
            prompt="hi",
            attachments=[att],
            thread="t1",
            working_dir=wd,
            model_id=None,
        )
    except ValueError as exc:
        assert "executable" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
