"""Filesystem-oriented CLI tools (read / write / list / grep / edit / glob / move / delete / mkdir / rmdir)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from .safety import SafetyContext, resolve_safe_path

_DEFAULT_READ_LIMIT = 64_000

# Skip dirs aligned with ``grep_files`` walker / ripgrep ``--glob`` exclusions.
_SKIP_DIR_NAMES = frozenset({".git", "__pycache__", "node_modules", ".venv"})


def _path_has_skip_dir(path: Path) -> bool:
    return any(part in _SKIP_DIR_NAMES for part in path.parts)


def _atomic_write_text(path: Path, content: str) -> None:
    """Write *content* via temp file + replace (best-effort atomic)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _grep_via_rg(pattern: str, root: Path, lim: int) -> str | None:
    import shutil

    rg = shutil.which("rg")
    if not rg:
        return None
    try:
        proc = subprocess.run(  # noqa: S603
            [
                rg,
                "-n",
                "-S",
                "--glob",
                "!.git/**",
                "--glob",
                "!node_modules/**",
                "--glob",
                "!.venv/**",
                pattern,
                str(root),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):  # 1 = no matches
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return "grep_files: no matches" if proc.returncode == 1 else None
    lines = out.splitlines()
    if len(lines) > lim:
        return "\n".join(lines[:lim]) + f"\n… truncated at {lim} lines (ripgrep)"
    return "\n".join(lines)


def make_filesystem_tools(ctx: SafetyContext, *, max_read_bytes: int = _DEFAULT_READ_LIMIT) -> list:
    @tool
    def read_file(path: str, offset: int = 0, limit: int = 8000, line_numbers: bool = True) -> str:
        """Read a **byte slice** of a UTF-8 text file (not “N lines”).

        ``offset`` is the start byte in the file; ``limit`` is the maximum number of **bytes**
        to read (default ``8000`` ≈ one 8KiB chunk, not 8000 lines). Output may include a
        ``[agloom:tool_result]`` footer with ``complete=`` and a ``next offset=`` hint when the
        file continues — prefer **one** adequately sized read over many tiny reads unless you
        are deliberately paging. Line numbers in the body are computed from the file start and
        reflect logical lines inside the decoded slice.
        """
        off = max(0, offset)
        lim = max(1, min(limit, max_read_bytes))
        ln = line_numbers
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"read_file: {exc}"
        if not p.is_file():
            return f"read_file: not a file: {path!r}"
        try:
            raw = p.read_bytes()
        except OSError as exc:
            return f"read_file: {exc}"
        ctx.recently_read_paths.add(str(p.resolve()))
        if off >= len(raw):
            return f"[agloom:tool_result] complete=true\n(empty beyond offset {off}; file size {len(raw)} bytes)"
        chunk = raw[off : off + lim]
        text = chunk.decode("utf-8", errors="replace")
        done = off + len(chunk) >= len(raw)
        tail = "" if done else f"\n\n… truncated (next offset={off + len(chunk)}, total_bytes={len(raw)})"
        if ln:
            start_line = raw[:off].count(b"\n") + 1
            out_lines = []
            for i, line in enumerate(text.splitlines(), start=start_line):
                out_lines.append(f"{i:6d}|{line}")
            body = "\n".join(out_lines)
        else:
            body = text
        return f"[agloom:tool_result] complete={str(done).lower()}\n{body}{tail}"

    @tool
    def write_file(path: str, content: str, force: bool = False) -> str:
        """Create or overwrite a text file. If the file exists, call ``read_file`` on this path first
        in the same session, or pass ``force=True`` to overwrite without reading."""
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"write_file: {exc}"
        if p.exists() and p.is_dir():
            return "write_file: target is a directory"
        key = str(p.resolve())
        if p.exists() and not force and key not in ctx.recently_read_paths:
            return (
                "write_file: file exists — run read_file on this path first in this session, "
                "or pass force=True to overwrite."
            )
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content or "", encoding="utf-8")
        except OSError as exc:
            return f"write_file: {exc}"
        try:
            rel = p.relative_to(ctx.root.resolve()) if ctx.sandbox else p
        except ValueError:
            rel = p
        return f"✓ wrote {rel}"

    def _lang_hint(rel: str) -> str:
        ext = Path(rel).suffix.lower()
        return {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".md": "markdown",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".rs": "rust",
            ".go": "go",
        }.get(ext, "text")

    @tool
    def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str | dict[str, Any]:
        """Replace ``old_string`` with ``new_string`` in a file (first occurrence unless replace_all)."""
        if not old_string:
            return "edit_file: old_string must be non-empty"
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"edit_file: {exc}"
        if not p.is_file():
            return f"edit_file: not a file: {path!r}"
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            return f"edit_file: {exc}"
        if old_string not in text:
            return "edit_file: old_string not found in file"
        if replace_all:
            new_text = text.replace(old_string, new_string)
            n = text.count(old_string)
        else:
            new_text = text.replace(old_string, new_string, 1)
            n = 1
        try:
            _atomic_write_text(p, new_text)
        except OSError as exc:
            return f"edit_file: {exc}"
        ctx.recently_read_paths.add(str(p.resolve()))
        summary = f"✓ edit_file: applied replacement ({n} occurrence(s))"
        try:
            rel = str(p.relative_to(ctx.root.resolve()) if ctx.sandbox else p)
        except ValueError:
            rel = str(p)
        return {
            "summary": summary,
            "before": text,
            "after": new_text,
            "language": _lang_hint(rel),
        }

    @tool
    def multi_edit(path: str, edits_json: str) -> str | dict[str, Any]:
        """Apply multiple edits in order. *edits_json* is a JSON array of
        ``{"old_string","new_string","replace_all":false}`` objects."""
        try:
            raw = json.loads(edits_json or "[]")
        except json.JSONDecodeError as exc:
            return f"multi_edit: invalid JSON ({exc})"
        if not isinstance(raw, list) or not raw:
            return "multi_edit: expected a non-empty JSON array"
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"multi_edit: {exc}"
        if not p.is_file():
            return f"multi_edit: not a file: {path!r}"
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            return f"multi_edit: {exc}"
        before_snapshot = text
        applied = 0
        for i, ed in enumerate(raw):
            if not isinstance(ed, dict):
                return f"multi_edit: edit[{i}] must be an object"
            old = ed.get("old_string")
            new = ed.get("new_string")
            if not isinstance(old, str) or not old:
                return f"multi_edit: edit[{i}].old_string required"
            if not isinstance(new, str):
                return f"multi_edit: edit[{i}].new_string must be a string"
            ra = bool(ed.get("replace_all", False))
            if old not in text:
                return f"multi_edit: edit[{i}] old_string not found"
            if ra:
                c = text.count(old)
                text = text.replace(old, new)
                applied += c
            else:
                text = text.replace(old, new, 1)
                applied += 1
        try:
            _atomic_write_text(p, text)
        except OSError as exc:
            return f"multi_edit: {exc}"
        ctx.recently_read_paths.add(str(p.resolve()))
        summary = f"✓ multi_edit: {applied} replacement(s) across {len(raw)} edit(s)"
        try:
            rel = str(p.relative_to(ctx.root.resolve()) if ctx.sandbox else p)
        except ValueError:
            rel = str(p)
        return {
            "summary": summary,
            "before": before_snapshot,
            "after": text,
            "language": _lang_hint(rel),
        }

    @tool
    def glob_files(pattern: str, path: str = ".") -> str:
        """Glob files under *path* (relative to working dir). Use ``**`` for recursive (e.g. ``**/*.py``).

        Skips ``.git``, ``node_modules``, ``__pycache__``, and ``.venv`` path segments (same as ``grep_files``).
        """
        pat = (pattern or "").strip() or "*"
        try:
            base = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"glob_files: {exc}"
        if not base.is_dir():
            return f"glob_files: not a directory: {path!r}"
        try:
            root_res = ctx.root.resolve()
            matches = sorted(
                {
                    str(p.relative_to(root_res))
                    for p in base.glob(pat)
                    if p.is_file() and not _path_has_skip_dir(p.relative_to(base))
                }
            )
        except OSError as exc:
            return f"glob_files: {exc}"
        if len(matches) > 500:
            return "\n".join(matches[:500]) + f"\n… {len(matches) - 500} more paths omitted"
        return "\n".join(matches) if matches else "glob_files: no matches"

    @tool
    def delete_file(path: str) -> str:
        """Delete a file (not a directory)."""
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"delete_file: {exc}"
        if not p.is_file():
            return f"delete_file: not a file: {path!r}"
        try:
            p.unlink()
        except OSError as exc:
            return f"delete_file: {exc}"
        ctx.recently_read_paths.discard(str(p.resolve()))
        return f"✓ deleted {p}"

    @tool
    def move_file(source_path: str, destination_path: str) -> str:
        """Rename or move a file within the working directory.

        Registers the destination path for ``write_file`` overwrite policy (same as after ``read_file``).
        """
        try:
            src = resolve_safe_path(source_path, ctx)
            dst = resolve_safe_path(destination_path, ctx)
        except ValueError as exc:
            return f"move_file: {exc}"
        if not src.is_file():
            return f"move_file: source not a file: {source_path!r}"
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
        except OSError as exc:
            return f"move_file: {exc}"
        ctx.recently_read_paths.discard(str(src.resolve()))
        ctx.recently_read_paths.add(str(dst.resolve()))
        return f"✓ moved to {dst}"

    @tool
    def mkdir(path: str, parents: bool = True, exist_ok: bool = True) -> str:
        """Create a directory (and parents when *parents* is True)."""
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"mkdir: {exc}"
        if p.exists() and p.is_file():
            return f"mkdir: {path!r} exists and is a file"
        try:
            p.mkdir(parents=parents, exist_ok=exist_ok)
        except OSError as exc:
            return f"mkdir: {exc}"
        try:
            rel = p.relative_to(ctx.root.resolve()) if ctx.sandbox else p
        except ValueError:
            rel = p
        return f"✓ mkdir {rel}"

    @tool
    def rmdir(path: str, recursive: bool = False) -> str:
        """Remove a directory. Empty only unless *recursive* is True (deletes tree under sandbox)."""
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"rmdir: {exc}"
        if not p.exists():
            return f"rmdir: path does not exist: {path!r}"
        if not p.is_dir():
            return f"rmdir: not a directory: {path!r}"
        try:
            rel = p.relative_to(ctx.root.resolve()) if ctx.sandbox else p
        except ValueError:
            rel = p
        key = str(p.resolve())
        try:
            if recursive:
                shutil.rmtree(p)
            else:
                p.rmdir()
        except OSError as exc:
            hint = " (pass recursive=True to remove non-empty trees)" if not recursive else ""
            return f"rmdir: {exc}{hint}"
        ctx.recently_read_paths.discard(key)
        return f"✓ rmdir {rel}"

    @tool
    def list_dir(path: str = ".") -> str:
        """List files and directories under path (non-recursive)."""
        try:
            p = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"list_dir: {exc}"
        if not p.is_dir():
            return f"list_dir: not a directory: {path!r}"
        try:
            entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError as exc:
            return f"list_dir: {exc}"
        lines = []
        for e in entries[:500]:
            kind = "dir" if e.is_dir() else "file"
            lines.append(f"[{kind}] {e.name}")
        extra = "" if len(entries) <= 500 else f"\n… {len(entries) - 500} more entries omitted"
        return "\n".join(lines) + extra if lines else "(empty)"

    @tool
    def grep_files(pattern: str, path: str = ".", max_matches: int = 50) -> str:
        """Search recursively for *pattern* (regex). Uses ripgrep when available, else Python."""
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"grep_files: invalid regex: {exc}"
        lim = max(1, min(max_matches, 200))
        try:
            root = resolve_safe_path(path, ctx)
        except ValueError as exc:
            return f"grep_files: {exc}"
        if not root.exists():
            return f"grep_files: path does not exist: {path!r}"

        if root.is_dir():
            rg_out = _grep_via_rg(pattern, root, lim)
            if rg_out is not None:
                return rg_out

        matches: list[str] = []
        root_resolved = ctx.root.resolve()

        def rel_display(fp: Path) -> Path:
            try:
                return fp.relative_to(root_resolved) if ctx.sandbox else fp
            except ValueError:
                return fp

        try:

            def walk(cur: Path) -> None:
                if len(matches) >= lim:
                    return
                try:
                    for child in cur.iterdir():
                        if len(matches) >= lim:
                            return
                        if child.is_dir():
                            if child.name in _SKIP_DIR_NAMES:
                                continue
                            walk(child)
                        elif child.is_file():
                            try:
                                text = child.read_text(encoding="utf-8", errors="ignore")
                            except OSError:
                                continue
                            for i, line in enumerate(text.splitlines(), start=1):
                                if len(matches) >= lim:
                                    return
                                if rx.search(line):
                                    matches.append(f"{rel_display(child)}:{i}:{line[:500]}")
                except OSError:
                    return

            if root.is_file():
                try:
                    text = root.read_text(encoding="utf-8", errors="ignore")
                except OSError as exc:
                    return f"grep_files: {exc}"
                for i, line in enumerate(text.splitlines(), start=1):
                    if len(matches) >= lim:
                        break
                    if rx.search(line):
                        matches.append(f"{rel_display(root)}:{i}:{line[:500]}")
            elif root.is_dir():
                walk(root)
            else:
                return "grep_files: not a file or directory"
        except OSError as exc:
            return f"grep_files: {exc}"
        if not matches:
            return "grep_files: no matches"
        tail = "" if len(matches) < lim else f"\n… truncated at {lim} matches"
        return "\n".join(matches) + tail

    return [
        read_file,
        write_file,
        edit_file,
        multi_edit,
        glob_files,
        delete_file,
        move_file,
        mkdir,
        rmdir,
        list_dir,
        grep_files,
    ]
