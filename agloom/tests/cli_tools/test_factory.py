"""Built-in CLI tool factory."""

from __future__ import annotations

from pathlib import Path

from agloom.cli_tools import CLI_TOOL_NAMES, get_cli_tools


def test_get_cli_tools_default_names(tmp_path: Path) -> None:
    tools = get_cli_tools(working_dir=tmp_path, allow_shell=True, allow_network=True, sandbox=True)
    names = {t.name for t in tools}
    assert names <= CLI_TOOL_NAMES
    assert "read_file" in names
    assert "which" in names
    assert "mkdir" in names
    assert "execute" in names
    assert "bash" in names
    assert "bash_background" in names


def test_get_cli_tools_no_shell(tmp_path: Path) -> None:
    tools = get_cli_tools(working_dir=tmp_path, allow_shell=False)
    names = {t.name for t in tools}
    assert "execute" not in names
    assert "bash" not in names


def test_glob_files_skips_heavy_dirs(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("# ok", encoding="utf-8")
    junk_dir = tmp_path / "node_modules"
    junk_dir.mkdir()
    (junk_dir / "junk.js").write_text("// skip", encoding="utf-8")
    tools = get_cli_tools(working_dir=tmp_path, allow_shell=False, allow_network=False, sandbox=True)
    glob_tool = next(t for t in tools if t.name == "glob_files")
    out = glob_tool.invoke({"pattern": "**/*", "path": "."})
    assert "keep.py" in out
    assert "junk.js" not in out


def test_move_file_registers_destination_for_write_policy(tmp_path: Path) -> None:
    tools = get_cli_tools(working_dir=tmp_path, allow_shell=False, sandbox=True)
    by_name = {t.name: t for t in tools}
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    by_name["move_file"].invoke({"source_path": "a.txt", "destination_path": "b.txt"})
    out = by_name["write_file"].invoke({"path": "b.txt", "content": "bye"})
    assert "wrote" in out.lower()
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "bye"
