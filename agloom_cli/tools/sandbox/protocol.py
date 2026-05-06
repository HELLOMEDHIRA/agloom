"""Pluggable backend protocol (filesystem + optional shell).

Aligned with DeepAgents-style ``BackendProtocol`` / ``SandboxBackendProtocol`` shapes
without importing ``deepagents``. Use for typing, alternative backends (DB, remote VM), and tests.

Async helpers use :func:`asyncio.to_thread` and are optional for sync-first CLI code.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final, Literal, NotRequired, TypeAlias, TypedDict

logger = logging.getLogger(__name__)

FileFormat = Literal["v1", "v2"]
"""Storage format hint for persisted file payloads (optional, for future backends)."""

FileOperationError = Literal[
    "file_not_found",
    "permission_denied",
    "is_directory",
    "invalid_path",
]

FILE_NOT_FOUND: Final = "file_not_found"
PERMISSION_DENIED: Final = "permission_denied"
IS_DIRECTORY: Final = "is_directory"
INVALID_PATH: Final = "invalid_path"


@dataclass
class FileDownloadResponse:
    path: str
    content: bytes | None = None
    error: str | None = None


@dataclass
class FileUploadResponse:
    path: str
    error: str | None = None


class FileInfo(TypedDict, total=False):
    path: str
    is_dir: bool
    size: NotRequired[int]
    mtime: NotRequired[float]
    modified_at: NotRequired[str]


class GrepMatch(TypedDict):
    path: str
    line: int
    text: str


class FileData(TypedDict, total=False):
    content: str
    encoding: str
    created_at: NotRequired[str]
    modified_at: NotRequired[str]


@dataclass
class ReadResult:
    error: str | None = None
    file_data: FileData | None = None


@dataclass
class WriteResult:
    error: str | None = None
    path: str | None = None


@dataclass
class EditResult:
    error: str | None = None
    path: str | None = None
    occurrences: int | None = None


@dataclass
class LsResult:
    error: str | None = None
    entries: list[FileInfo] | None = None


@dataclass
class GrepResult:
    error: str | None = None
    matches: list[GrepMatch] | None = None


@dataclass
class GlobResult:
    error: str | None = None
    matches: list[FileInfo] | None = None


@dataclass
class ExecuteResponse:
    output: str
    exit_code: int | None = None
    truncated: bool = False


class BackendProtocol(ABC):
    """Abstract filesystem backend — uniform read/write/edit/grep/glob/ls/upload/download."""

    @abstractmethod
    def ls(self, path: str) -> LsResult:
        """List directory entries (virtual paths: ``/`` or ``/foo`` under backend root)."""

    @abstractmethod
    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        """Read file; ``offset`` = 0-based lines to skip, ``limit`` = max lines (text)."""

    @abstractmethod
    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        """Literal substring search; optional basename ``glob`` (e.g. ``*.py``)."""

    @abstractmethod
    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        """Glob under ``path`` (virtual root ``/``)."""

    @abstractmethod
    def write(self, file_path: str, content: str) -> WriteResult:
        """Create file; fail if it already exists."""

    @abstractmethod
    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Exact string replace (CRLF-aware in local implementation)."""

    @abstractmethod
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload bytes to paths (partial success per file)."""

    @abstractmethod
    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download file bytes (partial success per path)."""

    async def als(self, path: str) -> LsResult:
        return await asyncio.to_thread(self.ls, path)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return await asyncio.to_thread(self.read, file_path, offset, limit)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        return await asyncio.to_thread(self.grep, pattern, path, glob)

    async def aglob(self, pattern: str, path: str = "/") -> GlobResult:
        return await asyncio.to_thread(self.glob, pattern, path)

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return await asyncio.to_thread(self.write, file_path, content)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return await asyncio.to_thread(self.edit, file_path, old_string, new_string, replace_all)

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return await asyncio.to_thread(self.upload_files, files)

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return await asyncio.to_thread(self.download_files, paths)


class SandboxBackendProtocol(BackendProtocol):
    """Backend + shell ``execute`` (containers, local host, SSH, …)."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Stable instance id for logging / routing."""

    @abstractmethod
    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Run a shell command in the backend environment."""

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)


@lru_cache(maxsize=128)
def execute_accepts_timeout(cls: type[SandboxBackendProtocol]) -> bool:
    """Whether ``cls.execute`` accepts a ``timeout`` keyword (for compat with older backends)."""
    try:
        sig = inspect.signature(cls.execute)
    except (ValueError, TypeError):
        logger.warning(
            "Could not inspect signature of %s.execute; assuming timeout unsupported.",
            getattr(cls, "__qualname__", cls),
            exc_info=True,
        )
        return False
    return "timeout" in sig.parameters


BackendFactory: TypeAlias = Callable[[Any], BackendProtocol]
"""Callable that returns a backend (e.g. receives a LangChain ``ToolRuntime`` in some stacks)."""

BACKEND_TYPES: TypeAlias = BackendProtocol | BackendFactory

__all__ = [
    "BACKEND_TYPES",
    "BackendFactory",
    "BackendProtocol",
    "EditResult",
    "ExecuteResponse",
    "FILE_NOT_FOUND",
    "FileData",
    "FileDownloadResponse",
    "FileFormat",
    "FileInfo",
    "FileOperationError",
    "FileUploadResponse",
    "GlobResult",
    "GrepMatch",
    "GrepResult",
    "INVALID_PATH",
    "IS_DIRECTORY",
    "LsResult",
    "PERMISSION_DENIED",
    "ReadResult",
    "SandboxBackendProtocol",
    "WriteResult",
    "execute_accepts_timeout",
]
