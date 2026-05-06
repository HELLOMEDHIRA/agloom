"""File system operations — cross-platform support."""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TypeAlias

from .sandbox.file_edit import match_edit_variants
from ..tool_loader import tool

# Groq (and some models) often emit "true"/"false" strings for booleans; JSON Schema must allow them.
BoolLike: TypeAlias = bool | str | int


def _boolish(value: BoolLike | None, *, default: bool = False) -> bool:
    """Coerce LLM/tool JSON booleans that arrive as strings or ints."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("0", "false", "no", "off", ""):
            return False
        if s in ("1", "true", "yes", "on"):
            return True
    return default

_MAX_READ_BYTES = 10 * 1024 * 1024  # 10 MB — prevent memory exhaustion
_MAX_GREP_FILE_BYTES = 2 * 1024 * 1024
_MAX_GREP_MATCHES_DEFAULT = 200
_SKIP_GREP_DIR_NAMES = frozenset(
    {".git", "__pycache__", ".venv", "venv", "node_modules", ".agloom", ".tox", "dist", "build"}
)


@tool
async def read_file(
    path: str,
    encoding: str = "utf-8",
    max_size: int = 1024 * 1024,
    offset: int = 1,
    limit: int | None = None,
) -> str:
    """Read the contents of a file (full or a line range).

    Relative paths resolve against the process working directory (see session **Shell cwd** in the
    prompt). If you get "File not found", call **get_working_directory**, **list_directory**, or use
    an absolute path — do not invent file contents.

    Args:
        path: Absolute or relative path to the file
        encoding: File encoding (default: utf-8)
        max_size: Maximum file size to read in bytes (default: 1MB)
        offset: 1-based starting line number (inclusive). Default 1 = from the beginning.
        limit: Maximum number of lines to return. Omit or null for all lines after ``offset``.

    Returns:
        File text, or a line-numbered slice when ``offset`` > 1 or ``limit`` is set.
    """
    try:
        if offset < 1:
            return "Error: offset must be >= 1 (1-based line number)."
        if limit is not None and limit < 1:
            return "Error: limit must be >= 1 when provided."

        file_path = _resolve_path(path)
        size = file_path.stat().st_size
        if size > max_size:
            return (
                f"Error: File too large ({size} bytes). Max allowed: {max_size} bytes. "
                "Increase max_size or use grep_files with a smaller scope."
            )
        text = file_path.read_text(encoding=encoding)
        if offset == 1 and limit is None:
            return text

        lines = text.splitlines()
        n = len(lines)
        if n == 0:
            if offset == 1:
                return ""
            return f"Error: offset {offset} is past end of file (0 lines)."

        if offset > n:
            return f"Error: offset {offset} is past end of file ({n} lines)."

        end_idx = n if limit is None else min(n, offset - 1 + limit)
        chunk = lines[offset - 1 : end_idx]
        partial = limit is not None and end_idx < n
        numbered = offset > 1 or limit is not None or partial

        body = "\n".join(f"{offset + i}|{line}" for i, line in enumerate(chunk))
        if partial:
            remaining = n - end_idx
            body += f"\n... ({remaining} more lines in file; use offset={end_idx + 1} to continue)"
        return body
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except UnicodeDecodeError as e:
        return f"Error: Could not decode file as {encoding}: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


@tool
async def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    encoding: str = "utf-8",
    replace_all: BoolLike = False,
) -> str:
    """Replace exact text in a file (search-and-replace).

    ``old_string`` must match the file byte-for-byte including whitespace. If it appears more than
    once, either add surrounding context so the match is unique or set ``replace_all`` true.

    Args:
        path: File to edit
        old_string: Text to find (must appear exactly once unless replace_all)
        new_string: Replacement text
        encoding: File encoding (default: utf-8)
        replace_all: Replace every occurrence of ``old_string``

    Returns:
        Success summary or an error message
    """
    try:
        if not old_string:
            return "Error: old_string must be non-empty."
        file_path = _resolve_path(path)
        if not file_path.is_file():
            return f"Error: Not a file or does not exist: {path}"
        size = file_path.stat().st_size
        if size > _MAX_READ_BYTES:
            return f"Error: File too large to edit safely ({size} bytes). Max: {_MAX_READ_BYTES}."
        text = file_path.read_text(encoding=encoding)
        m = match_edit_variants(old_string, new_string, text)
        if m is None:
            return (
                "Error: old_string not found in file. "
                "Use read_file to copy the exact snippet (including indentation and newlines)."
            )
        mo, mn, count = m
        ra = _boolish(replace_all, default=False)
        if count > 1 and not ra:
            return (
                f"Error: old_string matched {count} times — ambiguous. "
                "Provide a longer unique snippet or set replace_all true."
            )
        new_text = text.replace(mo, mn) if ra else text.replace(mo, mn, 1)
        file_path.write_text(new_text, encoding=encoding)
        replaced = count if ra else 1
        return f"Successfully edited {path} ({replaced} replacement(s), {len(new_text)} characters)."
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except UnicodeDecodeError as e:
        return f"Error: Could not decode file as {encoding}: {e}"
    except Exception as e:
        return f"Error editing file: {e}"


@tool
async def grep_files(
    pattern: str,
    path: str = ".",
    glob_pattern: str = "**/*",
    regex: BoolLike = True,
    ignore_case: BoolLike = False,
    max_matches: int = _MAX_GREP_MATCHES_DEFAULT,
) -> str:
    """Search file contents for a pattern (like ripgrep).

    Scans text files under ``path`` whose paths match ``glob_pattern``. Binary-looking files
    (NUL in the first chunk) are skipped.

    Args:
        pattern: Regex pattern (default) or literal string if ``regex`` is false
        path: Root directory to search
        glob_pattern: Pathlib glob relative to root (e.g. ``**/*.py``, ``*.md``)
        regex: If false, ``pattern`` is treated as a literal substring
        ignore_case: Case-insensitive match
        max_matches: Stop after this many matching lines (default 200)

    Returns:
        Lines formatted as ``relative/path:line:content``, or a message if nothing matched
    """
    try:
        if not pattern:
            return "Error: pattern must be non-empty."
        if max_matches < 1:
            return "Error: max_matches must be >= 1."
        root = _resolve_path(path)
        if not root.is_dir():
            return f"Error: Not a directory: {path}"

        flags = re.IGNORECASE if _boolish(ignore_case, default=False) else 0
        try:
            rx = re.compile(pattern if _boolish(regex, default=True) else re.escape(pattern), flags)
        except re.error as e:
            return f"Error: invalid pattern: {e}"

        out_lines: list[str] = []
        n_matches = 0
        for file_path in _iter_grep_files(root, glob_pattern):
            if n_matches >= max_matches:
                break
            try:
                raw = file_path.read_bytes()
            except OSError:
                continue
            if len(raw) > _MAX_GREP_FILE_BYTES:
                continue
            if b"\x00" in raw[:8192]:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = raw.decode("utf-8", errors="replace")
                except Exception:
                    continue
            rel = file_path.relative_to(root).as_posix()
            for i, line in enumerate(text.splitlines(), start=1):
                if n_matches >= max_matches:
                    break
                if rx.search(line):
                    out_lines.append(f"{rel}:{i}:{line}")
                    n_matches += 1

        if not out_lines:
            return f"No matches for pattern in {path!r} (glob {glob_pattern!r})."

        footer = ""
        if n_matches >= max_matches:
            footer = f"\n... (stopped at {max_matches} matches; narrow glob or pattern)"
        return "\n".join(out_lines) + footer
    except Exception as e:
        return f"Error grepping: {e}"


@tool
async def write_file(
    path: str, content: str, encoding: str = "utf-8", append: BoolLike = False
) -> str:
    """Write content to a file.

    Args:
        path: Absolute or relative path to the file
        content: Content to write
        encoding: File encoding (default: utf-8)
        append: If true, append to file instead of overwriting (default: false)

    Returns:
        Success or error message
    """
    try:
        file_path = _resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if _boolish(append, default=False) else "w"
        with open(file_path, mode, encoding=encoding) as f:
            f.write(content)

        return f"Successfully wrote to {path} ({len(content)} characters)"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
async def list_directory(path: str = ".", pattern: str = "*") -> str:
    """List files and directories in a folder.

    Args:
        path: Directory path (default: current directory)
        pattern: Glob pattern to filter files (default: * for all)

    Returns:
        Formatted list of files and directories
    """
    try:
        dir_path = _resolve_path(path)
        if not dir_path.is_dir():
            return f"Error: Not a directory: {path}"

        items = []
        for item in sorted(dir_path.glob(pattern)):
            rel = item.relative_to(dir_path)
            if item.is_dir():
                items.append(f"{rel}/")
            else:
                size = item.stat().st_size
                items.append(f"{rel} ({_format_size(size)})")

        if not items:
            return f"No files matching '{pattern}' in {path}"

        return "\n".join(items)
    except FileNotFoundError:
        return f"Error: Directory not found: {path}"
    except Exception as e:
        return f"Error listing directory: {e}"


@tool
async def file_exists(path: str) -> str:
    """Check if a file or directory exists.

    Args:
        path: Path to check

    Returns:
        "true" if exists, "false" if not
    """
    return "true" if _resolve_path(path).exists() else "false"


@tool
async def create_directory(path: str, parents: BoolLike = True) -> str:
    """Create a directory.

    Args:
        path: Directory path to create
        parents: Create parent directories if needed (default: true)

    Returns:
        Success or error message
    """
    try:
        dir_path = _resolve_path(path)
        dir_path.mkdir(parents=_boolish(parents, default=True), exist_ok=True)
        return f"Directory created: {path}"
    except Exception as e:
        return f"Error creating directory: {e}"


@tool
async def remove_file(path: str, recursive: BoolLike = False) -> str:
    """Remove a file or directory.

    Args:
        path: Path to remove
        recursive: If true, remove directories recursively (default: false). Accepts boolean or "true"/"false".

    Returns:
        Success or error message
    """
    try:
        file_path = _resolve_path(path)
        if not file_path.exists():
            return f"Error: Path does not exist: {path}"

        rec = _boolish(recursive, default=False)
        if file_path.is_dir():
            if rec:
                shutil.rmtree(file_path)
                return f"Directory removed: {path}"
            return f"Error: Use recursive=True to remove directory: {path}"
        file_path.unlink()
        return f"File removed: {path}"
    except Exception as e:
        return f"Error removing: {e}"


@tool
async def copy_file(source: str, destination: str, overwrite: BoolLike = False) -> str:
    """Copy a file or directory.

    Args:
        source: Source path
        destination: Destination path
        overwrite: Overwrite if destination exists (default: False)

    Returns:
        Success or error message
    """
    try:
        src = _resolve_path(source)
        dst = _resolve_path(destination)
        ow = _boolish(overwrite, default=False)

        if not src.exists():
            return f"Error: Source does not exist: {source}"

        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            if dst.exists():
                if not ow:
                    return f"Error: Destination exists: {destination}"
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            return f"Directory copied: {source} → {destination}"

        if dst.exists() and not ow:
            return f"Error: Destination exists: {destination}"

        shutil.copy2(src, dst)
        return f"File copied: {source} → {destination}"
    except Exception as e:
        return f"Error copying: {e}"


@tool
async def move_file(source: str, destination: str, overwrite: BoolLike = False) -> str:
    """Move a file or directory.

    Args:
        source: Source path
        destination: Destination path
        overwrite: Overwrite if destination exists (default: False)

    Returns:
        Success or error message
    """
    try:
        src = _resolve_path(source)
        dst = _resolve_path(destination)
        ow = _boolish(overwrite, default=False)

        if not src.exists():
            return f"Error: Source does not exist: {source}"

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists() and not ow:
            return f"Error: Destination exists: {destination}"

        shutil.move(str(src), str(dst))
        return f"Moved: {source} → {destination}"
    except Exception as e:
        return f"Error moving: {e}"


@tool
async def get_file_info(path: str) -> str:
    """Get detailed information about a file or directory.

    Args:
        path: Path to get info for

    Returns:
        Formatted file/directory information
    """
    try:
        file_path = _resolve_path(path)
        if not file_path.exists():
            return f"Error: Path does not exist: {path}"

        stat = file_path.stat()
        info = [
            f"Path: {file_path.absolute()}",
            f"Type: {'directory' if file_path.is_dir() else 'file'}",
            f"Size: {_format_size(stat.st_size)}",
        ]

        if not file_path.is_dir():
            info.append(f"Created: {_format_time(stat.st_ctime)}")
            info.append(f"Modified: {_format_time(stat.st_mtime)}")
            info.append(f"Accessed: {_format_time(stat.st_atime)}")

        return "\n".join(info)
    except Exception as e:
        return f"Error getting info: {e}"


@tool
async def search_files(
    path: str = ".",
    pattern: str = "*",
    recursive: BoolLike = True,
    file_only: BoolLike = True,
) -> str:
    """Search for files matching a pattern.

    Args:
        path: Directory to search in
        pattern: Glob pattern to match
        recursive: Search recursively (default: True)
        file_only: Only return files, not directories (default: True)

    Returns:
        List of matching paths
    """
    try:
        search_path = _resolve_path(path)
        if not search_path.is_dir():
            return f"Error: Not a directory: {path}"

        rec = _boolish(recursive, default=True)
        files_only = _boolish(file_only, default=True)
        matches = search_path.rglob(pattern) if rec else search_path.glob(pattern)

        results = []
        for match in sorted(matches):
            if files_only and match.is_dir():
                continue
            try:
                rel = match.relative_to(search_path)
                results.append(str(rel))
            except ValueError:
                results.append(str(match))

        if not results:
            return f"No files matching '{pattern}' found in {path}"

        return "\n".join(results)
    except Exception as e:
        return f"Error searching: {e}"


# Helpers


def _iter_grep_files(root: Path, glob_pattern: str) -> Iterator[Path]:
    """Yield files under *root* matching *glob_pattern*, skipping noisy directories."""
    for p in root.glob(glob_pattern):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            continue
        if any(part in _SKIP_GREP_DIR_NAMES for part in rel_parts):
            continue
        yield p


def _resolve_path(path: str) -> Path:
    """Resolve a path relative to the current working directory.

    Relative paths are anchored at cwd and are rejected if `..` segments
    escape that root (mitigates prompt-injection-driven traversal).
    Absolute paths are returned as-is — user-explicit and out of scope.
    """
    p = Path(path)
    if p.is_absolute():
        return p
    cwd = Path.cwd().resolve()
    resolved = (cwd / p).resolve()
    try:
        resolved.relative_to(cwd)
    except ValueError as exc:
        raise ValueError(f"Path traversal blocked: {path!r} resolves outside {cwd}") from exc
    return resolved


def _format_size(size: float) -> str:
    """Format file size in human-readable form."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _format_time(timestamp: float) -> str:
    """Format timestamp as readable date/time."""
    from datetime import datetime

    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")
