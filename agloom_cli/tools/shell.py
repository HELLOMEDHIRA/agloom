"""Shell command execution — cross-platform support.

Security
--------
These helpers invoke the **system shell** (`asyncio.create_subprocess_shell`, ``subprocess.run(..., shell=True)``).
They are intended for **trusted, local developer** sessions (for example the agloom CLI coding assistant).
Feeding untrusted user input into ``command`` can lead to **command injection** and full host compromise.

Mitigations: disable or gate shell tools in exposed deployments, require explicit approval for destructive
commands, run agents with least-privilege OS users, and never point agents at secrets or production
systems without review. See ``SECURITY.md`` at the repository root for reporting vulnerabilities.

"""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess

from ..safety_limits import RUN_SHELL_INCOMPLETE_PREVIEW_BYTES, RUN_SHELL_MAX_OUTPUT_BYTES
from ..tool_loader import tool
from ..tool_result_envelope import render_incomplete

_SHELL_HINTS = [
    "Do **not** treat the preview as full stdout/stderr.",
    "Redirect to a file (e.g. `cmd > out.txt`) and use read_file with offset/limit, or narrow with head/tail/grep.",
]
_MAX_ENV_VALUE_CHARS = 100
_REDACT_PATTERNS = ("key", "token", "secret", "password", "passwd", "auth", "cookie", "bearer")


def _should_redact_env(name: str) -> bool:
    n = name.lower()
    return any(p in n for p in _REDACT_PATTERNS)


def _redact(value: str) -> str:
    if not value:
        return value
    return "[REDACTED]"


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
        timeout: Timeout in seconds (default: 30, must be > 0)
        cwd: Working directory for the command
        env: Additional environment variables

    Returns:
        Command output (stdout + stderr)
    """
    if timeout <= 0:
        return "Error: Timeout must be a positive integer"

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
        except TimeoutError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                pass  # process reaped by OS eventually
            return f"Error: Command timed out after {timeout} seconds"

        out_len = len(stdout or b"")
        err_len = len(stderr or b"")
        if out_len > RUN_SHELL_MAX_OUTPUT_BYTES or err_len > RUN_SHELL_MAX_OUTPUT_BYTES:
            prv_out = (stdout or b"")[:RUN_SHELL_INCOMPLETE_PREVIEW_BYTES].decode("utf-8", errors="replace")
            prv_err = (stderr or b"")[:RUN_SHELL_INCOMPLETE_PREVIEW_BYTES].decode("utf-8", errors="replace")
            blob = "[stdout preview]\n" + prv_out
            if prv_err.strip():
                blob += "\n\n[stderr preview]\n" + prv_err
            return render_incomplete(
                kind="run_shell_output_bytes_cap",
                metrics={
                    "stdout_bytes": out_len,
                    "stderr_bytes": err_len,
                    "bytes_cap": RUN_SHELL_MAX_OUTPUT_BYTES,
                    "preview_bytes": RUN_SHELL_INCOMPLETE_PREVIEW_BYTES,
                },
                hints=_SHELL_HINTS,
                preview=blob,
            )

        result_parts = []

        if stdout:
            result_parts.append(stdout.decode("utf-8", errors="replace"))

        if stderr:
            err_text = stderr.decode("utf-8", errors="replace")
            if err_text:
                result_parts.append(f"[stderr] {err_text}")

        if proc.returncode != 0:
            result_parts.append(f"[exit code: {proc.returncode}]")

        return "\n".join(result_parts) if result_parts else "(no output)"

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
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr] {result.stderr}")
        parts.append(f"[exit code: {result.returncode}]")

        return "\n".join(parts)

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
            out_val = value
            if _should_redact_env(key):
                out_val = _redact(out_val)
            elif len(out_val) > _MAX_ENV_VALUE_CHARS:
                out_val = out_val[:_MAX_ENV_VALUE_CHARS] + "..."
            matches.append(f"{key}={out_val}")

    return "\n".join(matches) if matches else "No matching variables"


# Helpers


def _merge_env(extra: dict[str, str] | None) -> dict[str, str] | None:
    """Merge extra env vars with current environment."""
    if extra is None:
        return None

    env = os.environ.copy()
    env.update(extra)
    return env
