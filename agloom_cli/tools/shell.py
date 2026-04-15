"""Shell command execution — cross-platform support."""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
from typing import Any

from ..tool_loader import tool


@tool
async def run_shell(
    command: str,
    timeout: int = 30,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Execute a shell command and return its output.

    Args:
        command: Shell command to execute
        timeout: Timeout in seconds (default: 30)
        cwd: Working directory for the command
        env: Additional environment variables

    Returns:
        Command output (stdout + stderr)
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=_merge_env(env),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: Command timed out after {timeout} seconds"

        result_parts = []

        if stdout:
            result_parts.append(stdout.decode("utf-8", errors="replace"))

        if stderr:
            err_text = stderr.decode("utf-8", errors="replace")
            if err_text:
                result_parts.append(f"[stderr] {err_text}")

        if proc.returncode != 0:
            result_parts.append(f"[exit code: {proc.returncode}]")

        return result_parts[0] if result_parts else "(no output)"

    except FileNotFoundError:
        return f"Error: Command not found: {command.split()[0]}"
    except PermissionError:
        return f"Error: Permission denied: {command}"
    except Exception as e:
        return f"Error executing command: {e}"


@tool
async def run_shell_interactive(
    command: str,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Execute a shell command interactively (for long-running commands).

    Note: This runs synchronously and blocks. Use for interactive programs
    like editors (vim, nano) or package managers (apt, pip).

    Args:
        command: Shell command to execute
        cwd: Working directory for the command
        env: Additional environment variables

    Returns:
        Command exit status
    """
    try:
        merged_env = _merge_env(env)

        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=merged_env,
            text=True,
        )

        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(f"[stderr] {result.stderr}", file=__import__("sys").stderr)

        return f"[exit code: {result.returncode}]"

    except FileNotFoundError:
        return f"Error: Command not found: {command.split()[0]}"
    except Exception as e:
        return f"Error: {e}"


@tool
async def get_system_info() -> str:
    """Get system information (OS, architecture, etc.).

    Returns:
        Formatted system information
    """
    info = [
        f"OS: {platform.system()} {platform.release()}",
        f"Architecture: {platform.machine()}",
        f"Python: {platform.python_version()}",
    ]

    if platform.system() == "Linux":
        try:
            import distro

            info.append(f"Distro: {distro.name()} {distro.version()}")
        except ImportError:
            pass

    return "\n".join(info)


@tool
async def get_env_var(name: str, default: str = "") -> str:
    """Get an environment variable.

    Args:
        name: Environment variable name
        default: Default value if not set

    Returns:
        Variable value or default
    """
    return os.environ.get(name, default)


@tool
async def set_env_var(name: str, value: str) -> str:
    """Set an environment variable (current process only).

    Args:
        name: Environment variable name
        value: Value to set

    Returns:
        Success message
    """
    os.environ[name] = value
    return f"Set {name}={value}"


@tool
async def list_env_vars(pattern: str = "*") -> str:
    """List environment variables matching a pattern.

    Args:
        pattern: Glob pattern to match variable names

    Returns:
        List of matching variables
    """
    import fnmatch

    matches = []
    for key, value in sorted(os.environ.items()):
        if fnmatch.fnmatch(key.lower(), pattern.lower()):
            if len(value) > 100:
                value = value[:100] + "..."
            matches.append(f"{key}={value}")

    return "\n".join(matches) if matches else "No matching variables"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _merge_env(extra: dict[str, str] | None) -> dict[str, str] | None:
    """Merge extra env vars with current environment."""
    if extra is None:
        return None

    env = os.environ.copy()
    env.update(extra)
    return env
