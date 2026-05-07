"""Sandbox backends: protocol, local rooted FS, local shell.

Prefer importing from the parent package::

    from agloom_cli.tools import BackendProtocol, LocalSandbox, LocalShellBackend

- :class:`~agloom_cli.tools.sandbox.protocol.BackendProtocol` / :class:`~agloom_cli.tools.sandbox.protocol.SandboxBackendProtocol` — pluggable file + optional execute API.
- :class:`LocalSandbox` — rooted filesystem + minimal ``execute``.
- :class:`LocalShellBackend` — same files + rich local shell (env, caps, stderr tags).

Use HITL when exposing shell or file tools to models.
"""

from __future__ import annotations

from .file_edit import match_edit_variants
from .local import (
    MAX_BINARY_BYTES,
    MAX_OUTPUT_BYTES,
    TRUNCATION_MSG,
    LocalSandbox,
)
from .local_shell import DEFAULT_EXECUTE_TIMEOUT, LocalShellBackend
from .protocol import (
    BACKEND_TYPES,
    FILE_NOT_FOUND,
    INVALID_PATH,
    IS_DIRECTORY,
    PERMISSION_DENIED,
    BackendFactory,
    BackendProtocol,
    EditResult,
    ExecuteResponse,
    FileData,
    FileDownloadResponse,
    FileFormat,
    FileInfo,
    FileOperationError,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
    execute_accepts_timeout,
)

__all__ = [
    "BACKEND_TYPES",
    "DEFAULT_EXECUTE_TIMEOUT",
    "FILE_NOT_FOUND",
    "INVALID_PATH",
    "IS_DIRECTORY",
    "MAX_BINARY_BYTES",
    "MAX_OUTPUT_BYTES",
    "PERMISSION_DENIED",
    "TRUNCATION_MSG",
    "BackendFactory",
    "BackendProtocol",
    "EditResult",
    "ExecuteResponse",
    "FileData",
    "FileDownloadResponse",
    "FileFormat",
    "FileInfo",
    "FileOperationError",
    "FileUploadResponse",
    "GlobResult",
    "GrepMatch",
    "GrepResult",
    "LocalSandbox",
    "LocalShellBackend",
    "LsResult",
    "ReadResult",
    "SandboxBackendProtocol",
    "WriteResult",
    "execute_accepts_timeout",
    "match_edit_variants",
]
