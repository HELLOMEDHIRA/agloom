"""Working directory management — cross-platform support."""

from __future__ import annotations

import os
from pathlib import Path

from ..tool_loader import tool

_cwd_stack: list[str] = []


@tool
async def get_working_directory() -> str:
    """Get the current working directory.

    Returns:
        Current working directory as absolute path
    """
    return str(Path.cwd().resolve())


@tool
async def set_working_directory(path: str, create_if_missing: bool = False) -> str:
    """Change the current working directory.

    Args:
        path: Directory path to change to
        create_if_missing: Create directory if it doesn't exist (default: False)

    Returns:
        New working directory or error message
    """
    try:
        target = Path(path)

        if not target.is_absolute():
            target = Path.cwd() / target

        if not target.exists():
            if create_if_missing:
                target.mkdir(parents=True, exist_ok=True)
            else:
                return f"Error: Directory does not exist: {path}"

        if not target.is_dir():
            return f"Error: Not a directory: {path}"

        os.chdir(target)
        return f"Working directory changed to: {target.resolve()}"

    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: {e}"


@tool
async def push_working_directory(path: str) -> str:
    """Push current directory to stack and change to new directory.

    Args:
        path: Directory path to change to

    Returns:
        New working directory
    """
    global _cwd_stack

    current = str(Path.cwd().resolve())
    _cwd_stack.append(current)

    return await set_working_directory(path)


@tool
async def pop_working_directory() -> str:
    """Pop previous directory from stack and change to it.

    Returns:
        New working directory or error if stack is empty
    """
    global _cwd_stack

    if not _cwd_stack:
        return "Error: No previous directories in stack"

    previous = _cwd_stack.pop()
    os.chdir(previous)
    return f"Returned to: {previous}"


@tool
async def path_join(*parts: str) -> str:
    """Join path components.

    Args:
        *parts: Path components to join

    Returns:
        Joined path
    """
    return str(Path(*parts))


@tool
async def path_parent(path: str, levels: int = 1) -> str:
    """Get parent directory of a path.

    Args:
        path: Path to get parent of
        levels: Number of levels to go up (default: 1)

    Returns:
        Parent directory path
    """
    p = Path(path)
    for _ in range(levels):
        p = p.parent
    return str(p)


@tool
async def path_absolute(path: str) -> str:
    """Get absolute path.

    Args:
        path: Path to convert to absolute

    Returns:
        Absolute path
    """
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str((Path.cwd() / p).resolve())


@tool
async def path_exists(path: str) -> str:
    """Check if a path exists.

    Args:
        path: Path to check

    Returns:
        "true" if exists, "false" if not
    """
    return "true" if Path(path).exists() else "false"


@tool
async def path_is_file(path: str) -> str:
    """Check if path is a file.

    Args:
        path: Path to check

    Returns:
        "true" if file, "false" if not
    """
    return "true" if Path(path).is_file() else "false"


@tool
async def path_is_directory(path: str) -> str:
    """Check if path is a directory.

    Args:
        path: Path to check

    Returns:
        "true" if directory, "false" if not
    """
    return "true" if Path(path).is_dir() else "false"


@tool
async def path_basename(path: str) -> str:
    """Get the base name of a path (filename or last component).

    Args:
        path: Path to get basename of

    Returns:
        Base name
    """
    return Path(path).name


@tool
async def path_extension(path: str) -> str:
    """Get the file extension.

    Args:
        path: Path to get extension of

    Returns:
        Extension (including dot) or empty string
    """
    ext = Path(path).suffix
    return ext


@tool
async def path_stem(path: str) -> str:
    """Get the file name without extension.

    Args:
        path: Path to get stem of

    Returns:
        Filename without extension
    """
    return Path(path).stem
