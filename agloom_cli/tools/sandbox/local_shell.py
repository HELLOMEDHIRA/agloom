"""Local shell backend: confined filesystem API + unrestricted host ``execute``.

:class:`LocalShellBackend` subclasses :class:`LocalSandbox` so **read / write / edit /
grep / glob / ls** stay under ``root_dir``, while **shell** commands run on the host with
``shell=True`` and can access **any** path unless the OS user cannot — same trust model as
DeepAgents ``LocalShellBackend``.

**Use HITL** when exposing this to an LLM; shell bypasses filesystem path guards.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Final

from .local import LocalSandbox
from .protocol import ExecuteResponse

DEFAULT_EXECUTE_TIMEOUT: Final = 120
"""Default timeout in seconds for :meth:`LocalShellBackend.execute`."""


class LocalShellBackend(LocalSandbox):
    """Filesystem operations under ``root_dir`` plus full local ``execute``.

    - File APIs use the same rooted paths as :class:`LocalSandbox`.
    - ``execute`` uses ``cwd=root_dir``, optional custom ``env``, stdin closed (``DEVNULL``),
      combined stdout/stderr (stderr lines prefixed with ``[stderr] ``), output byte cap,
      and non-zero exit codes annotated with ``Exit code: N``.

    This does **not** sandbox the process: commands run as the current user.
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        *,
        timeout: int = DEFAULT_EXECUTE_TIMEOUT,
        max_output_bytes: int = 100_000,
        env: dict[str, str] | None = None,
        inherit_env: bool = False,
    ) -> None:
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        root = Path(root_dir).resolve() if root_dir is not None else Path.cwd().resolve()
        super().__init__(root)
        self._default_timeout = timeout
        self._max_output_bytes = max_output_bytes
        if inherit_env:
            self._cmd_env = os.environ.copy()
            if env:
                self._cmd_env.update(env)
        else:
            self._cmd_env = dict(env) if env else {}
        self._instance_id = f"local-{uuid.uuid4().hex[:8]}"

    @property
    def id(self) -> str:
        return self._instance_id

    @property
    def cwd(self) -> Path:
        """Working directory for shell commands (same as :attr:`LocalSandbox.root`)."""
        return self._root

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        if not command or not isinstance(command, str):
            return ExecuteResponse(
                output="Error: Command must be a non-empty string.",
                exit_code=1,
                truncated=False,
            )

        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout <= 0:
            raise ValueError(f"timeout must be positive, got {effective_timeout}")

        try:
            result = subprocess.run(
                command,
                check=False,
                shell=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=effective_timeout,
                env=self._cmd_env,
                cwd=str(self._root),
                encoding="utf-8",
                errors="replace",
            )

            output_parts: list[str] = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                for line in result.stderr.rstrip("\n").split("\n"):
                    output_parts.append(f"[stderr] {line}")

            output = "\n".join(output_parts) if output_parts else "<no output>"
            truncated = False
            if len(output.encode("utf-8")) > self._max_output_bytes:
                raw = output.encode("utf-8")[: self._max_output_bytes]
                output = raw.decode("utf-8", errors="ignore")
                output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."
                truncated = True

            if result.returncode != 0:
                output = f"{output.rstrip()}\n\nExit code: {result.returncode}"

            return ExecuteResponse(
                output=output,
                exit_code=result.returncode,
                truncated=truncated,
            )

        except subprocess.TimeoutExpired:
            msg = (
                f"Error: Command timed out after {effective_timeout} seconds. "
                "For long-running commands, pass a larger timeout to execute()."
            )
            return ExecuteResponse(output=msg, exit_code=124, truncated=False)
        except Exception as e:
            return ExecuteResponse(
                output=f"Error executing command ({type(e).__name__}): {e}",
                exit_code=1,
                truncated=False,
            )
