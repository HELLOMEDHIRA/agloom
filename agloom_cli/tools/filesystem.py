"""File system operations — cross-platform support."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..tool_loader import tool

_MAX_READ_BYTES = 10 * 1024 * 1024  # 10 MB — prevent memory exhaustion


@tool
async def read_file(path: str, encoding: str = "utf-8", max_size: int = 1024 * 1024) -> str:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to the file
        encoding: File encoding (default: utf-8)
        max_size: Maximum file size to read in bytes (default: 1MB)

    Returns:
        The contents of the file as a string
    """
    try:
        file_path = _resolve_path(path)
        size = file_path.stat().st_size
        if size > max_size:
            return f"Error: File too large ({size} bytes). Max allowed: {max_size} bytes. Use max_size parameter to override."
        return file_path.read_text(encoding=encoding)
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except UnicodeDecodeError as e:
        return f"Error: Could not decode file as {encoding}: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


@tool
async def write_file(path: str, content: str, encoding: str = "utf-8", append: bool = False) -> str:
    """Write content to a file.

    Args:
        path: Absolute or relative path to the file
        content: Content to write
        encoding: File encoding (default: utf-8)
        append: If True, append to file instead of overwriting (default: False)

    Returns:
        Success or error message
    """
    try:
        file_path = _resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
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
async def create_directory(path: str, parents: bool = True) -> str:
    """Create a directory.

    Args:
        path: Directory path to create
        parents: Create parent directories if needed (default: True)

    Returns:
        Success or error message
    """
    try:
        dir_path = _resolve_path(path)
        dir_path.mkdir(parents=parents, exist_ok=True)
        return f"Directory created: {path}"
    except Exception as e:
        return f"Error creating directory: {e}"


@tool
async def remove_file(path: str, recursive: bool = False) -> str:
    """Remove a file or directory.

    Args:
        path: Path to remove
        recursive: If True, remove directories recursively (default: False)

    Returns:
        Success or error message
    """
    try:
        file_path = _resolve_path(path)
        if not file_path.exists():
            return f"Error: Path does not exist: {path}"

        if file_path.is_dir():
            if recursive:
                shutil.rmtree(file_path)
                return f"Directory removed: {path}"
            return f"Error: Use recursive=True to remove directory: {path}"
        file_path.unlink()
        return f"File removed: {path}"
    except Exception as e:
        return f"Error removing: {e}"


@tool
async def copy_file(source: str, destination: str, overwrite: bool = False) -> str:
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

        if not src.exists():
            return f"Error: Source does not exist: {source}"

        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            if dst.exists():
                if not overwrite:
                    return f"Error: Destination exists: {destination}"
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            return f"Directory copied: {source} → {destination}"

        if dst.exists() and not overwrite:
            return f"Error: Destination exists: {destination}"

        shutil.copy2(src, dst)
        return f"File copied: {source} → {destination}"
    except Exception as e:
        return f"Error copying: {e}"


@tool
async def move_file(source: str, destination: str, overwrite: bool = False) -> str:
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

        if not src.exists():
            return f"Error: Source does not exist: {source}"

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists() and not overwrite:
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
    recursive: bool = True,
    file_only: bool = True,
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

        matches = search_path.rglob(pattern) if recursive else search_path.glob(pattern)

        results = []
        for match in sorted(matches):
            if file_only and match.is_dir():
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
