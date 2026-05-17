"""Per-tool behavior for ``get_cli_tools`` (filesystem, shell, web)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agloom.cli_tools import get_cli_tools
from agloom.models import ExecutionResult, PatternType


def _tools(tmp_path: Path, *, shell: bool = True, network: bool = True):
    return {t.name: t for t in get_cli_tools(working_dir=tmp_path, allow_shell=shell, allow_network=network, sandbox=True)}


def test_edit_file_old_string_not_found(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    t = _tools(tmp_path)["edit_file"]
    out = t.invoke({"path": "a.txt", "old_string": "nope", "new_string": "x"})
    assert "not found" in out.lower()
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_edit_file_replace_all(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("foo foo foo", encoding="utf-8")
    t = _tools(tmp_path)["edit_file"]
    out = t.invoke({"path": "a.txt", "old_string": "foo", "new_string": "bar", "replace_all": True})
    summary = out["summary"] if isinstance(out, dict) else out
    assert "✓" in summary or "applied" in summary.lower()
    assert (tmp_path / "a.txt").read_text() == "bar bar bar"


def test_multi_edit_ordered_and_abort_before_write(tmp_path: Path) -> None:
    (tmp_path / "m.txt").write_text("aaa\nbbb\n", encoding="utf-8")
    me = _tools(tmp_path)["multi_edit"]
    bad = '[{"old_string":"aaa","new_string":"AAA"},{"old_string":"zzz","new_string":"ZZZ"}]'
    out = me.invoke({"path": "m.txt", "edits_json": bad})
    assert "not found" in out.lower()
    assert (tmp_path / "m.txt").read_text() == "aaa\nbbb\n"

    good = '[{"old_string":"aaa","new_string":"AAA"},{"old_string":"bbb","new_string":"BBB"}]'
    out2 = me.invoke({"path": "m.txt", "edits_json": good})
    s2 = out2["summary"] if isinstance(out2, dict) else out2
    assert "✓" in s2 or "replacement" in s2.lower()
    assert (tmp_path / "m.txt").read_text() == "AAA\nBBB\n"


def test_read_file_line_numbers_and_offset(tmp_path: Path) -> None:
    raw = "line1\nline2\nline3\n"
    (tmp_path / "r.txt").write_text(raw, encoding="utf-8")
    rf = _tools(tmp_path)["read_file"]
    chunk = b"line2\nline3\n"
    off = raw.encode().find(chunk)
    out = rf.invoke({"path": "r.txt", "offset": off, "limit": 1000, "line_numbers": True})
    assert "line2" in out
    assert "|line2" in out  # ``cat -n`` style column


def test_read_file_line_cap_trims_logical_lines(tmp_path: Path) -> None:
    content = "\n".join(f"row{i}" for i in range(1, 31)) + "\n"
    (tmp_path / "many.txt").write_text(content, encoding="utf-8")
    rf = _tools(tmp_path)["read_file"]
    out = rf.invoke(
        {"path": "many.txt", "offset": 0, "limit": 8000, "line_numbers": True, "line_cap": 5},
    )
    assert "row1" in out
    assert "row5" in out
    assert "|row6" not in out
    assert "limited to first 5" in out.lower()


def test_write_file_requires_read_first(tmp_path: Path) -> None:
    (tmp_path / "w.txt").write_text("orig", encoding="utf-8")
    wf = _tools(tmp_path)["write_file"]
    out = wf.invoke({"path": "w.txt", "content": "new", "force": False})
    assert "read_file" in out.lower() or "exists" in out.lower()
    assert (tmp_path / "w.txt").read_text() == "orig"

    ok = wf.invoke({"path": "w.txt", "content": "new", "force": True})
    assert "wrote" in ok.lower()
    assert (tmp_path / "w.txt").read_text() == "new"


def test_mkdir_and_rmdir(tmp_path: Path) -> None:
    ts = _tools(tmp_path)
    ts["mkdir"].invoke({"path": "nest/a", "parents": True})
    assert (tmp_path / "nest" / "a").is_dir()
    ts["rmdir"].invoke({"path": "nest/a", "recursive": False})
    assert not (tmp_path / "nest" / "a").exists()


def test_which_finds_python(tmp_path: Path) -> None:
    w = _tools(tmp_path)["which"]
    name = Path(sys.executable).name
    out = w.invoke({"executable": name})
    assert not out.lower().startswith("which:")
    assert "not found" not in out.lower()


def test_delete_file_discards_recent_read(tmp_path: Path) -> None:
    (tmp_path / "d.txt").write_text("x", encoding="utf-8")
    ts = _tools(tmp_path)
    ts["read_file"].invoke({"path": "d.txt"})
    ts["delete_file"].invoke({"path": "d.txt"})
    assert not (tmp_path / "d.txt").exists()


@patch("agloom.cli_tools.shell.subprocess.run")
def test_execute_uses_argv_not_shell(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
    ex = _tools(tmp_path)["execute"]
    py = sys.executable
    ex.invoke({"command": f'{py} -c "print(42)"'})
    assert mock_run.called
    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("shell") is False


@patch("agloom.cli_tools.shell.subprocess.run")
def test_bash_uses_shell_true(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
    bash = _tools(tmp_path)["bash"]
    py = sys.executable
    bash.invoke({"command": f'{py} -c "print(42)"'})
    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("shell") is True


@patch("agloom.cli_tools.shell.subprocess.Popen")
def test_bash_background_start_status_stop(mock_popen: MagicMock, tmp_path: Path) -> None:
    proc = MagicMock()
    proc.pid = 4242
    proc.poll.side_effect = [None, None, 0]
    proc.wait.return_value = 0
    mock_popen.return_value = proc
    ts = _tools(tmp_path)
    start = ts["bash_background"].invoke({"command": "sleep 99"})
    m = re.search(r"job_id=([a-f0-9]+)", start)
    assert m
    jid = m.group(1)
    st = ts["bash_background_status"].invoke({"job_id": jid})
    assert "running" in st
    sp = ts["bash_background_stop"].invoke({"job_id": jid})
    assert "stopped" in sp.lower() or jid in sp


@patch("agloom.cli_tools.shell.subprocess.Popen")
@patch("agloom.cli_tools.shell.os.name", new="nt")
def test_bash_background_stop_escalates_kill_after_term_timeout(mock_popen: MagicMock, tmp_path: Path) -> None:
    proc = MagicMock()
    proc.pid = 4242
    proc.poll.side_effect = [None, -9]
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="sh", timeout=2),
        None,
    ]
    mock_popen.return_value = proc
    ts = _tools(tmp_path)
    start = ts["bash_background"].invoke({"command": "sleep 99"})
    m = re.search(r"job_id=([a-f0-9]+)", start)
    assert m
    ts["bash_background_stop"].invoke({"job_id": m.group(1)})
    proc.kill.assert_called_once()


@patch("httpx.AsyncClient")
@pytest.mark.asyncio
async def test_fetch_url_extract_readable_toggle(mock_client_cls: MagicMock, tmp_path: Path) -> None:
    html_body = b"<html><body><p>Hello</p><script>x</script></body></html>"

    def _ctx():
        resp = MagicMock()
        resp.status_code = 200
        resp.content = html_body
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        inner = MagicMock()
        inner.get = AsyncMock(return_value=resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=inner)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_client_cls.return_value = _ctx()
    ft = _tools(tmp_path, network=True)["fetch_url"]
    plain = await ft.ainvoke({"url": "https://example.com/x", "extract_readable_text": True})
    assert "hello" in plain.lower()
    assert "<script>" not in plain.lower()

    mock_client_cls.return_value = _ctx()
    rawish = await ft.ainvoke({"url": "https://example.com/x", "extract_readable_text": False})
    assert "<html>" in rawish.lower()


@patch("httpx.AsyncClient")
@patch("agloom.cli_tools.web._try_trafilatura_extract", return_value="TRAFILATURA_MAIN_BODY")
@pytest.mark.asyncio
async def test_read_url_markdown_prefers_trafilatura_when_available(
    mock_traf: MagicMock, mock_client_cls: MagicMock, tmp_path: Path
) -> None:
    html_body = b"<html><body><nav>skip</nav><p>Hello</p></body></html>"

    def _ctx():
        resp = MagicMock()
        resp.status_code = 200
        resp.content = html_body
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        inner = MagicMock()
        inner.get = AsyncMock(return_value=resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=inner)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_client_cls.return_value = _ctx()
    rum = _tools(tmp_path, network=True)["read_url_markdown"]
    out = await rum.ainvoke({"url": "https://example.com/article"})
    assert "TRAFILATURA_MAIN_BODY" in out


@patch("httpx.AsyncClient")
@patch("agloom.cli_tools.web._try_trafilatura_extract", return_value=None)
@pytest.mark.asyncio
async def test_read_url_markdown_falls_back_when_trafilatura_none(
    mock_traf: MagicMock, mock_client_cls: MagicMock, tmp_path: Path
) -> None:
    html_body = b"<html><body><p>FallbackHello</p></body></html>"

    def _ctx():
        resp = MagicMock()
        resp.status_code = 200
        resp.content = html_body
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        inner = MagicMock()
        inner.get = AsyncMock(return_value=resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=inner)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_client_cls.return_value = _ctx()
    rum = _tools(tmp_path, network=True)["read_url_markdown"]
    out = await rum.ainvoke({"url": "https://example.com/page"})
    assert "fallbackhello" in out.lower()


@pytest.mark.asyncio
async def test_task_tool_invokes_delegate(tmp_path: Path) -> None:
    from agloom.delegation import HandoffTarget
    from agloom.unified_agent import create_agent

    sub = MagicMock()
    sub.name = "worker"
    sub.ainvoke = AsyncMock(
        return_value=ExecutionResult(
            pattern_used=PatternType.REACT,
            query="q",
            output="from-sub",
            success=True,
        ),
    )
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    agent = await create_agent(
        model=llm,
        name="main",
        cli_tools={"working_dir": str(tmp_path), "allow_shell": False, "allow_network": False, "sandbox": True},
        delegates=[HandoffTarget(sub, name="worker", description="test worker")],
    )
    task_tool = next(t for t in agent.config["tools"] if t.name == "task")
    out = await task_tool.ainvoke({"prompt": "do thing", "delegate_name": "worker"})
    assert out == "from-sub"
    sub.ainvoke.assert_awaited()


@pytest.mark.asyncio
async def test_task_tool_no_delegate_message(tmp_path: Path) -> None:
    from agloom.unified_agent import create_agent

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    agent = await create_agent(
        model=llm,
        name="solo",
        cli_tools={"working_dir": str(tmp_path), "allow_shell": False, "allow_network": False, "sandbox": True},
    )
    task_tool = next(t for t in agent.config["tools"] if t.name == "task")
    out = await task_tool.ainvoke({"prompt": "hello"})
    assert "task:" in out.lower()
    assert "delegate" in out.lower() or "matching" in out.lower()
