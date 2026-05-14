"""MCP specs from nested ``agloom.yaml`` when ``--mcp`` argv is empty."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from agloom.runtime.serve_cli import mcp_configs_from_args, mcp_specs_from_agloom_yaml


def test_mcp_specs_from_nested_yaml(tmp_path: Path) -> None:
    dot = tmp_path / ".agloom"
    dot.mkdir()
    y = dot / "agloom.yaml"
    y.write_text(
        "mcp:\n  servers:\n    - demo:mcp/demo.yaml\n",
        encoding="utf-8",
    )
    (dot / "mcp").mkdir()
    demo = dot / "mcp" / "demo.yaml"
    demo.write_text(
        "name: demo\ntransport: stdio\ncommand: echo\nargs: []\n",
        encoding="utf-8",
    )
    specs = mcp_specs_from_agloom_yaml(tmp_path)
    assert len(specs) == 1
    assert specs[0].startswith("demo:")
    assert str(demo.resolve()) in specs[0]


def test_mcp_configs_merge_yaml_when_argv_empty(tmp_path: Path) -> None:
    dot = tmp_path / ".agloom"
    dot.mkdir()
    y = dot / "agloom.yaml"
    y.write_text(
        "mcp:\n  servers:\n    - z:mcp/z.yaml\n",
        encoding="utf-8",
    )
    (dot / "mcp").mkdir()
    zpath = dot / "mcp" / "z.yaml"
    zpath.write_text(
        "name: z\ntransport: stdio\ncommand: echo\nargs: []\n",
        encoding="utf-8",
    )
    args = Namespace(mcp=[])
    cfgs = mcp_configs_from_args(args, cwd=tmp_path)
    assert len(cfgs) == 1
    assert cfgs[0].name == "z"
