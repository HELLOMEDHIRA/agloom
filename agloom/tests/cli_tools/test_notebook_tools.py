"""Tests for ``notebook_read`` / ``notebook_edit``."""

from __future__ import annotations

import json
from pathlib import Path

from agloom.cli_tools import get_cli_tools


def _by_name(tmp_path: Path):
    return {t.name: t for t in get_cli_tools(working_dir=tmp_path, allow_shell=False, allow_network=False, sandbox=True)}


def test_notebook_read_round_trip_format(tmp_path: Path) -> None:
    ipynb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": "# H\n"},
            {"cell_type": "code", "metadata": {}, "source": ["print(", "1", ")"], "outputs": [], "execution_count": None},
        ],
    }
    path = tmp_path / "a.ipynb"
    path.write_text(json.dumps(ipynb), encoding="utf-8")
    ts = _by_name(tmp_path)
    out = ts["notebook_read"].invoke({"path": "a.ipynb"})
    assert "--- cell 0 [markdown] ---" in out
    assert "# H" in out
    assert "--- cell 1 [code] ---" in out
    assert "print(1)" in out.replace("\n", "") or "print(" in out


def test_notebook_edit_requires_read_or_force(tmp_path: Path) -> None:
    path = tmp_path / "b.ipynb"
    path.write_text(
        json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}),
        encoding="utf-8",
    )
    ts = _by_name(tmp_path)
    edits = json.dumps([{"op": "insert_cell", "cell_index": 0, "cell_type": "markdown", "source": "x"}])
    out = ts["notebook_edit"].invoke({"path": "b.ipynb", "edits_json": edits})
    assert "notebook_read" in out.lower() or "force" in out.lower()

    ok = ts["notebook_edit"].invoke({"path": "b.ipynb", "edits_json": edits, "force": True})
    assert "OK:" in ok or "applied" in ok.lower()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["cells"]) == 1


def test_notebook_edit_sequence_insert_delete(tmp_path: Path) -> None:
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}
    path = tmp_path / "c.ipynb"
    path.write_text(json.dumps(nb), encoding="utf-8")
    ts = _by_name(tmp_path)
    ts["notebook_read"].invoke({"path": "c.ipynb"})
    seq = [
        {"op": "insert_cell", "cell_index": 0, "cell_type": "code", "source": "1"},
        {"op": "insert_cell", "cell_index": 1, "cell_type": "markdown", "source": "2"},
        {"op": "delete_cell", "cell_index": 0},
    ]
    out = ts["notebook_edit"].invoke({"path": "c.ipynb", "edits_json": json.dumps(seq)})
    assert "OK:" in out
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["cells"]) == 1
    assert data["cells"][0]["cell_type"] == "markdown"
    assert _src(data["cells"][0]) == "2"


def test_notebook_edit_aborts_before_disk_write(tmp_path: Path) -> None:
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [{"cell_type": "markdown", "metadata": {}, "source": "keep-me"}],
    }
    path = tmp_path / "abort.ipynb"
    path.write_text(json.dumps(nb), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    ts = _by_name(tmp_path)
    ts["notebook_read"].invoke({"path": "abort.ipynb"})
    edits = json.dumps(
        [
            {"op": "set_source", "cell_index": 0, "source": "mutated-in-memory-only"},
            {"op": "set_source", "cell_index": 9, "source": "bad-index"},
        ]
    )
    out = ts["notebook_edit"].invoke({"path": "abort.ipynb", "edits_json": edits})
    assert "out of range" in out.lower()
    assert path.read_text(encoding="utf-8") == before


def test_notebook_edit_set_source(tmp_path: Path) -> None:
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [{"cell_type": "code", "metadata": {}, "source": "0", "outputs": [], "execution_count": None}],
    }
    path = tmp_path / "d.ipynb"
    path.write_text(json.dumps(nb), encoding="utf-8")
    ts = _by_name(tmp_path)
    ts["notebook_read"].invoke({"path": "d.ipynb"})
    edits = json.dumps([{"op": "set_source", "cell_index": 0, "source": "print(99)\n"}])
    ts["notebook_edit"].invoke({"path": "d.ipynb", "edits_json": edits})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["cells"][0]["source"] == "print(99)\n"


def test_notebook_edit_creates_missing_file_with_force(tmp_path: Path) -> None:
    ts = _by_name(tmp_path)
    p = tmp_path / "new.ipynb"
    assert not p.exists()
    edits = json.dumps([{"op": "insert_cell", "cell_index": 0, "cell_type": "markdown", "source": "# New"}])
    ts["notebook_edit"].invoke({"path": "new.ipynb", "edits_json": edits, "force": True})
    assert p.is_file()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data["cells"]) == 1


def _src(cell: dict) -> str:
    s = cell.get("source")
    if isinstance(s, list):
        return "".join(s)
    return str(s or "")
