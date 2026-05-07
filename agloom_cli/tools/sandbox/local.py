"""Local sandbox: all paths under a root, operations in-process (no remote ``execute`` templates).

Implements :class:`~agloom_cli.tools.sandbox.protocol.SandboxBackendProtocol` with dataclass results.
Virtual paths use leading ``/`` as the sandbox root (e.g. ``/src/a.py`` → ``<root>/src/a.py``).
"""

from __future__ import annotations

import base64
import codecs
import fnmatch
import os
import subprocess
from pathlib import Path
from typing import Final, Literal

from .file_edit import match_edit_variants
from .protocol import (
    EditResult,
    ExecuteResponse,
    FileData,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
)

MAX_BINARY_BYTES: Final = 500 * 1024
MAX_OUTPUT_BYTES: Final = 500 * 1024
TRUNCATION_MSG: Final = (
    "\n\n[Output was truncated due to size limits. "
    "Continue with a larger offset or smaller limit.]"
)
_EDIT_INLINE_MAX_BYTES: Final = 50_000
_MAX_GREP_FILE_BYTES: Final = 2 * 1024 * 1024
_SKIP_NAMES: Final = frozenset(
    {".git", "__pycache__", ".venv", "venv", "node_modules", ".agloom", ".tox", "dist", "build"}
)

_BINARY_SUFFIXES: Final = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp3",
        ".mp4",
        ".webm",
        ".7z",
        ".rar",
    }
)


def _get_file_type(file_path: Path) -> Literal["text", "binary"]:
    suf = file_path.suffix.lower()
    if suf in _BINARY_SUFFIXES:
        return "binary"
    try:
        sample = file_path.read_bytes()[:8192]
    except OSError:
        return "binary"
    if b"\x00" in sample:
        return "binary"
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
    except UnicodeDecodeError:
        return "binary"
    return "text"


def _coerce_text(buf: object) -> str:
    """Best-effort coerce ``subprocess`` stdout/stderr (str | bytes | None) to ``str``."""
    if buf is None:
        return ""
    if isinstance(buf, bytes):
        return buf.decode("utf-8", errors="replace")
    return str(buf)


def _virt_rel(path: str | None) -> str:
    """Map virtual path (``/foo``) to relpath under sandbox root."""
    if path is None:
        return "."
    s = str(path).strip().replace("\\", "/")
    if s in ("/", ""):
        return "."
    if s.startswith("/"):
        s = s[1:]
    return s if s else "."


class LocalSandbox(SandboxBackendProtocol):
    """Sandbox rooted at ``root``; paths cannot escape. Minimal ``execute`` (see :class:`LocalShellBackend`)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def id(self) -> str:
        return "local"

    @property
    def root(self) -> Path:
        return self._root

    def _safe(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            r = p.resolve()
        else:
            r = (self._root / p).resolve()
        try:
            r.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(f"Path escapes sandbox root: {path!r}") from exc
        return r

    def _safe_virt(self, path: str | None) -> Path:
        return self._safe(_virt_rel(path))

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Run ``command`` in a shell with ``cwd`` = sandbox root (basic combined stdout/stderr)."""
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self._root,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return ExecuteResponse(output=out, exit_code=proc.returncode, truncated=False)
        except subprocess.TimeoutExpired as e:
            stdout = _coerce_text(e.stdout)
            stderr = _coerce_text(e.stderr)
            msg = stdout + stderr + "\n(timeout)"
            return ExecuteResponse(output=msg, exit_code=124, truncated=False)
        except Exception as e:
            return ExecuteResponse(output=str(e), exit_code=1, truncated=False)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        out: list[FileUploadResponse] = []
        for rel, data in files:
            try:
                dest = self._safe_virt(rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                out.append(FileUploadResponse(path=_virt_rel(rel)))
            except Exception as e:
                out.append(FileUploadResponse(path=_virt_rel(rel), error=str(e)))
        return out

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        out: list[FileDownloadResponse] = []
        for rel in paths:
            try:
                p = self._safe_virt(rel)
                if not p.is_file():
                    out.append(FileDownloadResponse(path=_virt_rel(rel), error="not a file"))
                    continue
                out.append(FileDownloadResponse(path=_virt_rel(rel), content=p.read_bytes()))
            except Exception as e:
                out.append(FileDownloadResponse(path=_virt_rel(rel), error=str(e)))
        return out

    def ls(self, path: str = "/") -> LsResult:
        try:
            d = self._safe_virt(path)
            if not d.is_dir():
                return LsResult(error=f"Not a directory: {path}", entries=None)
            entries: list[FileInfo] = []
            with os.scandir(d) as it:
                for e in it:
                    ep = Path(e.path).resolve()
                    try:
                        rel = ep.relative_to(self._root).as_posix()
                    except ValueError:
                        rel = str(ep)
                    info: FileInfo = {"path": rel, "is_dir": e.is_dir(follow_symlinks=False)}
                    entries.append(info)
            entries.sort(key=lambda x: x["path"].lower())
            return LsResult(entries=entries, error=None)
        except Exception as e:
            return LsResult(entries=None, error=str(e))

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ReadResult:
        try:
            if offset < 0 or limit < 1:
                return ReadResult(error="invalid offset or limit")
            p = self._safe_virt(file_path)
            if not p.is_file():
                return ReadResult(error="file_not_found")

            if p.stat().st_size == 0:
                fd: FileData = {
                    "content": "System reminder: File exists but has empty contents",
                    "encoding": "utf-8",
                }
                return ReadResult(file_data=fd)

            ftype = _get_file_type(p)
            if ftype == "binary":
                sz = p.stat().st_size
                if sz > MAX_BINARY_BYTES:
                    return ReadResult(
                        error=f"Binary file exceeds maximum preview size of {MAX_BINARY_BYTES} bytes",
                    )
                raw = p.read_bytes()
                return ReadResult(
                    file_data={
                        "content": base64.b64encode(raw).decode("ascii"),
                        "encoding": "base64",
                    },
                )

            msg_bytes = len(TRUNCATION_MSG.encode("utf-8"))
            effective_limit = MAX_OUTPUT_BYTES - msg_bytes
            parts: list[str] = []
            current_bytes = 0
            line_count = 0
            returned_lines = 0
            truncated = False

            with p.open("r", encoding="utf-8", newline="") as f:
                for raw_line in f:
                    line_count += 1
                    if line_count <= offset:
                        continue
                    if returned_lines >= limit:
                        break
                    line = raw_line.rstrip("\n").rstrip("\r")
                    piece = line if returned_lines == 0 else "\n" + line
                    piece_bytes = len(piece.encode("utf-8"))
                    if current_bytes + piece_bytes > effective_limit:
                        truncated = True
                        remaining = effective_limit - current_bytes
                        if remaining > 0:
                            prefix = piece.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
                            if prefix:
                                parts.append(prefix)
                                current_bytes += len(prefix.encode("utf-8"))
                        break
                    parts.append(piece)
                    current_bytes += piece_bytes
                    returned_lines += 1

            if returned_lines == 0 and not truncated:
                return ReadResult(
                    error=f"Line offset {offset} exceeds file length ({line_count} lines)",
                )

            text = "".join(parts)
            if truncated:
                text += TRUNCATION_MSG
            return ReadResult(file_data={"content": text, "encoding": "utf-8"})
        except Exception as e:
            return ReadResult(error=str(e))

    def _write_preflight(self, file_path: str) -> WriteResult | None:
        try:
            p = self._safe_virt(file_path)
            if p.exists():
                return WriteResult(error=f"Error: File already exists: {file_path!r}")
            p.parent.mkdir(parents=True, exist_ok=True)
            return None
        except Exception as e:
            return WriteResult(error=str(e))

    def write(self, file_path: str, content: str) -> WriteResult:
        pre = self._write_preflight(file_path)
        if pre is not None:
            return pre
        try:
            p = self._safe_virt(file_path)
            p.write_text(content, encoding="utf-8", newline="\n")
            return WriteResult(path=_virt_rel(file_path), error=None)
        except Exception as e:
            return WriteResult(error=str(e))

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        try:
            if not old_string:
                return EditResult(error="old_string must be non-empty")
            p = self._safe_virt(file_path)
            if not p.is_file():
                return EditResult(error=f"File '{file_path}' not found")

            payload = len(old_string.encode("utf-8")) + len(new_string.encode("utf-8"))
            if payload > _EDIT_INLINE_MAX_BYTES:
                return EditResult(
                    error=(
                        f"old+new payload ({payload} bytes) exceeds inline max "
                        f"{_EDIT_INLINE_MAX_BYTES}; split the edit or use smaller snippets."
                    ),
                )

            raw = p.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return EditResult(error=f"File '{file_path}' is not a text file")

            m = match_edit_variants(old_string, new_string, text)
            if m is None:
                return EditResult(error=f"String not found in file: {old_string!r}")
            mo, mn, count = m
            if count > 1 and not replace_all:
                return EditResult(
                    error=(
                        f"String appears {count} times. Use replace_all=True to replace all occurrences."
                    ),
                )
            result = text.replace(mo, mn) if replace_all else text.replace(mo, mn, 1)
            p.write_bytes(result.encode("utf-8"))
            return EditResult(
                path=_virt_rel(file_path),
                occurrences=count if replace_all else 1,
                error=None,
            )
        except Exception as e:
            return EditResult(error=str(e))

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        max_matches = 200
        if not pattern:
            return GrepResult(error="pattern must be non-empty", matches=None)
        root = self._safe_virt(path)
        if not root.is_dir():
            return GrepResult(error="path must be a directory", matches=None)
        matches: list[GrepMatch] = []
        n = 0
        needle = pattern

        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_NAMES]
            for name in filenames:
                if n >= max_matches:
                    break
                fp = Path(dirpath) / name
                try:
                    rel = fp.relative_to(self._root).as_posix()
                except ValueError:
                    continue
                if glob and not fnmatch.fnmatch(name, glob):
                    continue
                try:
                    if fp.stat().st_size > _MAX_GREP_FILE_BYTES:
                        continue
                except OSError:
                    continue
                try:
                    raw = fp.read_bytes()
                except OSError:
                    continue
                if b"\x00" in raw[:8192]:
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                for i, line in enumerate(text.splitlines(), start=1):
                    if n >= max_matches:
                        break
                    if needle in line:
                        matches.append({"path": rel, "line": i, "text": line})
                        n += 1
                if n >= max_matches:
                    break
            if n >= max_matches:
                break

        return GrepResult(matches=matches, error=None)

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        base = self._safe_virt(path)
        if not base.is_dir():
            return GlobResult(matches=None, error="path must be a directory")
        matches: list[FileInfo] = []
        try:
            for p in sorted(base.glob(pattern)):
                if any(part in _SKIP_NAMES for part in p.relative_to(base).parts):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                matches.append(
                    {
                        "path": str(p.relative_to(self._root)).replace("\\", "/"),
                        "is_dir": p.is_dir(),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    }
                )
            return GlobResult(matches=matches, error=None)
        except Exception as e:
            return GlobResult(matches=None, error=str(e))
