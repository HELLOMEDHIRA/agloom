"""Jupyter notebook tools (``.ipynb``) — read and structured edits without extra dependencies."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, cast

from langchain_core.tools import tool

from .safety import SafetyContext, resolve_safe_path


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _source_to_str(source: Any) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, list):
        return "".join(str(x) for x in source)
    return ""


def _normalize_cells(nb: dict[str, Any]) -> str | None:
    cells = nb.get("cells")
    if not isinstance(cells, list):
        return "notebook: invalid JSON — missing or invalid top-level 'cells' array"
    return None


def make_notebook_tools(ctx: SafetyContext) -> list[Any]:
    @tool
    def notebook_read(path: str, max_chars_per_cell: int = 24_000) -> str:
        """Load a Jupyter notebook (``.ipynb``) and return numbered cells (markdown/code/raw) with source text."""
        try:
            cap = max(256, min(int(max_chars_per_cell), 500_000))
        except (TypeError, ValueError):
            cap = 24_000
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"notebook_read: {exc}"
        if not p.is_file():
            return f"notebook_read: not a file: {path!r}"
        if p.suffix.lower() != ".ipynb":
            return "notebook_read: expected a path ending in .ipynb"
        try:
            raw = p.read_text(encoding="utf-8")
            nb = json.loads(raw)
        except json.JSONDecodeError as exc:
            return f"notebook_read: invalid JSON ({exc})"
        except OSError as exc:
            return f"notebook_read: {exc}"
        if not isinstance(nb, dict):
            return "notebook_read: root must be a JSON object"
        err = _normalize_cells(nb)
        if err:
            return err
        cells = nb["cells"]
        ctx.recently_read_paths.add(str(p.resolve()))
        lines: list[str] = []
        try:
            rel = p.relative_to(ctx.root.resolve()) if ctx.sandbox else p
        except ValueError:
            rel = p
        lines.append(f"[agloom:notebook_read] path={rel} cells={len(cells)}")
        for i, cell in enumerate(cells):
            if not isinstance(cell, dict):
                lines.append(f"\n--- cell {i} ERROR ---\n(not an object, skipped)")
                continue
            ct = str(cell.get("cell_type") or "?")
            src = _source_to_str(cell.get("source"))
            full_len = len(src)
            if full_len > cap:
                src = src[:cap] + f"\n… truncated ({full_len} chars → cap {cap})"
            lines.append(f"\n--- cell {i} [{ct}] ---\n{src}")
        out = "\n".join(lines)
        if len(out) > 120_000:
            return out[:120_000] + "\n… notebook_read: total output truncated"
        return out

    @tool
    def notebook_edit(path: str, edits_json: str, force: bool = False) -> str:
        """Apply edits to an ``.ipynb`` file. *edits_json* is a JSON array of operations applied **in order**
        (indices shift after ``insert_cell`` / ``delete_cell``).

        Operations:

        - ``{"op": "set_source", "cell_index": N, "source": "..."}`` — replace cell *N* source (markdown/code/raw).
        - ``{"op": "insert_cell", "cell_index": N, "cell_type": "markdown"|"code"|"raw", "source": "..."}`` —
          insert a new cell **before** index *N*; use *N* equal to current cell count to append.
        - ``{"op": "delete_cell", "cell_index": N}`` — remove cell *N*.

        Call ``notebook_read`` on this path first in the session, or pass ``force=True``.
        """
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"notebook_edit: {exc}"
        if p.suffix.lower() != ".ipynb":
            return "notebook_edit: expected a path ending in .ipynb"
        key = str(p.resolve())
        if p.exists() and not force and key not in ctx.recently_read_paths:
            return (
                "notebook_edit: call notebook_read on this path first in this session, "
                "or pass force=True."
            )
        try:
            ops = json.loads(edits_json or "[]")
        except json.JSONDecodeError as exc:
            return f"notebook_edit: invalid edits JSON ({exc})"
        if not isinstance(ops, list) or not ops:
            return "notebook_edit: expected a non-empty JSON array of operations"

        if p.exists():
            try:
                nb = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return f"notebook_edit: could not load notebook ({exc})"
        else:
            nb = {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [],
            }

        if not isinstance(nb, dict):
            return "notebook_edit: notebook root must be an object"
        err = _normalize_cells(nb)
        if err:
            return f"notebook_edit: {err.replace('notebook:', '').strip()}"
        raw_cells = nb.get("cells")
        if not isinstance(raw_cells, list):
            return "notebook_edit: cells must be an array"
        cells: list[Any] = cast("list[Any]", raw_cells)

        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                return f"notebook_edit: op[{i}] must be an object"
            kind = str(op.get("op") or "").strip()
            try:
                idx = op.get("cell_index")
                ci = int(idx) if idx is not None else -1
            except (TypeError, ValueError):
                return f"notebook_edit: op[{i}] invalid cell_index"

            if kind == "set_source":
                if not (0 <= ci < len(cells)):
                    return f"notebook_edit: op[{i}] cell_index {ci} out of range (0..{len(cells) - 1})"
                cell = cells[ci]
                if not isinstance(cell, dict):
                    return f"notebook_edit: op[{i}] cell {ci} is not an object"
                src = op.get("source")
                if not isinstance(src, str):
                    return f"notebook_edit: op[{i}] source must be a string"
                cell["source"] = src
            elif kind == "insert_cell":
                ct = str(op.get("cell_type") or "code").lower()
                if ct not in ("markdown", "code", "raw"):
                    return f"notebook_edit: op[{i}] cell_type must be markdown, code, or raw"
                src = op.get("source")
                if not isinstance(src, str):
                    return f"notebook_edit: op[{i}] source must be a string"
                if ci < 0 or ci > len(cells):
                    return f"notebook_edit: op[{i}] cell_index {ci} invalid for insert (0..{len(cells)})"
                new_cell: dict[str, Any] = {"cell_type": ct, "metadata": {}, "source": src}
                if ct == "code":
                    new_cell["outputs"] = []
                    new_cell["execution_count"] = None
                cells.insert(ci, new_cell)
            elif kind == "delete_cell":
                if not (0 <= ci < len(cells)):
                    return f"notebook_edit: op[{i}] cell_index {ci} out of range"
                del cells[ci]
            else:
                return f"notebook_edit: op[{i}] unknown op {kind!r} (use set_source, insert_cell, delete_cell)"

        nb["cells"] = cells
        nb.setdefault("nbformat", 4)
        nb.setdefault("nbformat_minor", 5)
        nb.setdefault("metadata", {})

        try:
            _atomic_write_json(p, nb)
        except OSError as exc:
            return f"notebook_edit: {exc}"

        ctx.recently_read_paths.add(key)
        try:
            rel = p.relative_to(ctx.root.resolve()) if ctx.sandbox else p
        except ValueError:
            rel = p
        return f"✓ notebook_edit: {len(ops)} operation(s) applied → {rel}"

    return [notebook_read, notebook_edit]
