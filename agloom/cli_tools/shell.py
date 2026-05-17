"""Shell execution tools (argv ``execute`` + ``bash`` + background shell), gated by HITL where noted."""

from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from typing import Any

from langchain_core.tools import tool

from .safety import BackgroundShellJob, SafetyContext, resolve_safe_path, split_command
from .subprocess_env import safe_subprocess_env

_MAX_BACKGROUND_JOBS = 16
_MAX_TOOL_OUTPUT_CHARS = 32_000
_MAX_TOOL_STDERR_CHARS = 8_000


def _cap_output(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _subprocess_env() -> dict[str, str]:
    """Fresh env snapshot for each subprocess (reflects current process env)."""
    return safe_subprocess_env()


def make_which_tools() -> list[Any]:
    """Resolve executables on ``PATH`` (always safe — no shell execution)."""

    @tool
    def which(executable: str) -> str:
        """Return the absolute path to *executable* on ``PATH`` (``shutil.which``), or *not found*."""
        import shutil

        name = (executable or "").strip()
        if not name:
            return "which: empty name"
        found = shutil.which(name)
        if not found:
            return f"which: {name!r} not found on PATH"
        return found

    return [which]


def make_shell_tool(ctx: SafetyContext, *, timeout_s: float = 120.0) -> list[Any]:
    @tool
    def execute(command: str) -> str:
        """Run a shell-less command (argv split) with cwd set to the session working directory.

        Redirections and pipes require ``bash`` — keep commands simple here (e.g. ``pytest -q``).
        """
        if not ctx.allow_shell:
            return "execute: shell tool disabled by runtime configuration"
        cmd = (command or "").strip()
        if not cmd:
            return "execute: empty command"
        try:
            cwd = resolve_safe_path(".", ctx)
            if not cwd.is_dir():
                return "execute: working directory is not a folder"
        except ValueError as exc:
            return f"execute: {exc}"
        try:
            argv = split_command(cmd)
        except ValueError as exc:
            return f"execute: could not parse command: {exc}"
        if not argv:
            return "execute: no argv after parsing"
        try:
            proc = subprocess.run(  # noqa: S603
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                shell=False,
                env=_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return f"execute: timed out after {timeout_s}s"
        except OSError as exc:
            return f"execute: {exc}"
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parts: list[str] = [f"exit={proc.returncode}"]
        if out:
            parts.append(_cap_output(out, _MAX_TOOL_OUTPUT_CHARS))
        if err:
            parts.append("stderr:\n" + _cap_output(err, _MAX_TOOL_STDERR_CHARS))
        return "\n".join(parts) if len(parts) > 1 else parts[0]

    @tool
    def bash(command: str) -> str:
        """Run a **real shell** command (``&&``, pipes, redirects). Inherently risky — same HITL gate as ``execute``.

        Each call runs in a **fresh** subshell with cwd reset to the session working directory;
        ``cd`` and similar effects do **not** carry over to later ``bash`` / ``execute`` calls.
        """
        if not ctx.allow_shell:
            return "bash: shell tool disabled by runtime configuration"
        cmd = (command or "").strip()
        if not cmd:
            return "bash: empty command"
        try:
            cwd = resolve_safe_path(".", ctx)
            if not cwd.is_dir():
                return "bash: working directory is not a folder"
        except ValueError as exc:
            return f"bash: {exc}"
        try:
            proc = subprocess.run(  # noqa: S602
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                shell=True,
                env=_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return f"bash: timed out after {timeout_s}s"
        except OSError as exc:
            return f"bash: {exc}"
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parts: list[str] = [f"exit={proc.returncode}"]
        if out:
            parts.append(_cap_output(out, _MAX_TOOL_OUTPUT_CHARS))
        if err:
            parts.append("stderr:\n" + _cap_output(err, _MAX_TOOL_STDERR_CHARS))
        return "\n".join(parts) if len(parts) > 1 else parts[0]

    @tool
    def bash_background(command: str) -> str:
        """Start a shell command in the background (does not block the agent).

        Stdout and stderr are discarded to avoid pipe deadlocks on long-running servers. Redirect to a
        file in *command* if you need logs (e.g. ``npm run dev > dev.log 2>&1``).

        Returns a ``job_id`` for ``bash_background_status`` / ``bash_background_stop``. Child
        processes started by the shell may not all stop on ``bash_background_stop`` on some OSes.
        """
        if not ctx.allow_shell:
            return "bash_background: shell tool disabled by runtime configuration"
        cmd = (command or "").strip()
        if not cmd:
            return "bash_background: empty command"
        if len(ctx.background_shell_jobs) >= _MAX_BACKGROUND_JOBS:
            return f"bash_background: too many active jobs (max {_MAX_BACKGROUND_JOBS})"
        try:
            cwd = resolve_safe_path(".", ctx)
            if not cwd.is_dir():
                return "bash_background: working directory is not a folder"
        except ValueError as exc:
            return f"bash_background: {exc}"

        popen_kw: dict[str, Any] = {
            "cwd": str(cwd),
            "shell": True,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": _subprocess_env(),
        }
        if os.name == "nt":
            win_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", None)
            if win_flags is not None:
                popen_kw["creationflags"] = win_flags
        else:
            popen_kw["start_new_session"] = True

        try:
            proc = subprocess.Popen(cmd, **popen_kw)  # noqa: S603
        except OSError as exc:
            return f"bash_background: {exc}"

        job_id = uuid.uuid4().hex[:12]
        ctx.background_shell_jobs[job_id] = BackgroundShellJob(
            proc=proc,
            command=cmd,
            started_at=time.time(),
        )
        return f"bash_background: started job_id={job_id}"

    @tool
    def bash_background_status(job_id: str) -> str:
        """Poll a background job: *running* or *exited* with exit code."""
        jid = (job_id or "").strip()
        if not jid:
            return "bash_background_status: empty job_id"
        entry = ctx.background_shell_jobs.get(jid)
        if entry is None:
            return "bash_background_status: unknown job_id"
        rc = entry.proc.poll()
        if rc is None:
            age = round(time.time() - entry.started_at, 1)
            return f"job_id={jid} status=running age_s={age} command={entry.command!r}"
        return f"job_id={jid} status=exited exit={rc} command={entry.command!r}"

    @tool
    def bash_background_stop(job_id: str) -> str:
        """Terminate a background job: SIGTERM / ``terminate``, wait up to 2s, then SIGKILL / ``kill``."""
        jid = (job_id or "").strip()
        if not jid:
            return "bash_background_stop: empty job_id"
        entry = ctx.background_shell_jobs.pop(jid, None)
        if entry is None:
            return "bash_background_stop: unknown job_id"
        proc = entry.proc
        done = proc.poll()
        if done is not None:
            return f"job_id={jid} already_exited exit={done}"

        pgid_for_kill: int | None = None
        try:
            if os.name != "nt":
                try:
                    getpgid = getattr(os, "getpgid", None)
                    killpg = getattr(os, "killpg", None)
                    sigterm = getattr(signal, "SIGTERM", None)
                    if getpgid is not None and killpg is not None and sigterm is not None:
                        pgid_for_kill = int(getpgid(proc.pid))
                        killpg(pgid_for_kill, sigterm)
                    else:
                        pgid_for_kill = None
                        proc.terminate()
                except (OSError, ProcessLookupError):
                    pgid_for_kill = None
                    proc.terminate()
            else:
                proc.terminate()

            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if pgid_for_kill is not None and os.name != "nt":
                    killpg = getattr(os, "killpg", None)
                    sigkill = getattr(signal, "SIGKILL", None)
                    if killpg is not None and sigkill is not None:
                        try:
                            killpg(pgid_for_kill, sigkill)
                        except (OSError, ProcessLookupError):
                            proc.kill()
                    else:
                        proc.kill()
                else:
                    proc.kill()
                try:
                    proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        except OSError as exc:
            return f"bash_background_stop: {exc}"

        final = proc.poll()
        return f"bash_background_stop: job_id={jid} stopped exit={final}"

    return [execute, bash, bash_background, bash_background_status, bash_background_stop]
