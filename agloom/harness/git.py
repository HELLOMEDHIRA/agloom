"""Structured git helpers for harnessed agents: status, log, commit, and checkpoint tags."""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..cli_tools.subprocess_env import safe_subprocess_env
from ..logging_utils import get_logger

logger = get_logger(__name__)

_MAX_STAGE_PATHS = 500

_CHECKPOINT_PREFIX = "agloom/"


def _sanitize_git_message(msg: str, *, max_len: int = 10_000) -> str:
    """Strip control characters that break ``git -m`` or inject misleading ``git log`` output."""
    s = msg.replace("\r\n", "\n").replace("\r", "\n")
    # Single-line subjects: flatten newlines in the first line for ``commit -m``.
    lines = s.split("\n", 1)
    first = lines[0].replace("\n", " ")
    rest = ("\n" + lines[1]) if len(lines) > 1 else ""
    s = first + rest
    out_chars: list[str] = []
    for ch in s[:max_len]:
        o = ord(ch)
        if ch == "\n" or o >= 32:
            out_chars.append(ch)
    return "".join(out_chars).strip() or "(empty message)"


@dataclass
class GitCommit:
    """A single git commit."""

    hash: str
    short_hash: str
    message: str
    author: str
    date: str
    files_changed: int = 0


@dataclass
class GitCheckpoint:
    """A named checkpoint tag."""

    name: str
    commit_hash: str
    description: str
    created_at: str
    session_id: str


@dataclass
class GitStatus:
    """Result of git status."""

    is_repo: bool
    clean: bool
    branch: str = ""
    staged: list[str] = field(default_factory=list)
    unstaged: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    ahead: int = 0
    behind: int = 0


class GitSession:
    """
    Structured git operations for agent sessions.

    All operations are async and run via subprocess. Failures are
    logged but never crash the run — git is optional infrastructure.

    Thread-safety:
      Uses a per-instance asyncio.Lock. Multiple agents writing to the
      same repo are serialized to avoid race conditions on commits.
    """

    def __init__(
        self,
        cwd: str | None = None,
        author_name: str = "agent",
        author_email: str = "agent@agloom.dev",
    ) -> None:
        self._cwd = cwd or "."
        self._author_name = author_name
        self._author_email = author_email
        self._lock: asyncio.Lock | None = None
        self._last_commit: str | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _author_env(self) -> dict[str, str]:
        return {"GIT_AUTHOR_NAME": self._author_name, "GIT_AUTHOR_EMAIL": self._author_email}

    def _git_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Conservative subprocess env — drop inherited GIT_* redirect vars."""
        env = safe_subprocess_env(self._author_env())
        for key in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_CONFIG",
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_SYSTEM",
        ):
            env.pop(key, None)
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        if extra:
            env.update(extra)
        return env

    async def _run(
        self,
        *args: str,
        check: bool = False,
        timeout: int = 30,
        env: dict | None = None,
    ) -> tuple[int, str, str]:
        """Run a git command. Returns (returncode, stdout, stderr)."""
        try:
            merged_env = self._git_env(env) if env is not None else self._git_env()
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=self._cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout = stdout_b.decode("utf-8", errors="replace").strip()
            stderr = stderr_b.decode("utf-8", errors="replace").strip()
            rc = proc.returncode or 0
            if rc != 0 and check:
                raise subprocess.CalledProcessError(rc, args, stdout, stderr)
            return rc, stdout, stderr
        except FileNotFoundError:
            return 1, "", "git: command not found"
        except TimeoutError:
            return 124, "", f"git {' '.join(args)}: timed out after {timeout}s"
        except Exception as exc:
            logger.warning(f"[Git] subprocess error: {exc!r}")
            return 1, "", str(exc)

    async def is_repo(self) -> bool:
        """Check if the working directory is a git repository."""
        rc, _, _ = await self._run("rev-parse", "--is-inside-work-tree")
        return rc == 0

    async def status(self) -> GitStatus:
        """
        Get the current git status.
        Returns GitStatus with clean=True if nothing to commit.
        """
        if not await self.is_repo():
            return GitStatus(is_repo=False, clean=False)

        rc, out, _ = await self._run("status", "--porcelain=v1", "-b")
        if rc != 0:
            return GitStatus(is_repo=True, clean=False)

        lines = out.splitlines()
        branch = ""
        staged, unstaged, untracked = [], [], []
        ahead, behind = 0, 0

        for line in lines:
            if line.startswith("##"):
                branch = line[3:].split("...")[0].strip()
                for part in line.split():
                    if part.startswith("ahead"):
                        try:
                            ahead = int(part.split("=")[1])
                        except Exception:
                            pass
                    elif part.startswith("behind"):
                        try:
                            behind = int(part.split("=")[1])
                        except Exception:
                            pass
            elif len(line) >= 2:
                index_st = line[0]
                worktree = line[1]
                path = line[3:]
                if index_st not in (" ", "?"):
                    staged.append(path)
                if worktree == "?":
                    untracked.append(path)
                elif worktree not in (" ", "?"):
                    unstaged.append(path)

        clean = not (staged or unstaged or untracked)
        return GitStatus(
            is_repo=True,
            clean=clean,
            branch=branch,
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
            ahead=ahead,
            behind=behind,
        )

    async def log(
        self,
        limit: int = 20,
        since: str = "",
    ) -> list[GitCommit]:
        """
        Get recent commits.

        Args:
            limit: Maximum number of commits to return.
            since: Optional --since date (e.g. '7 days ago').
        """
        if not await self.is_repo():
            return []

        args = [
            "log",
            "--format=%H|%h|%s|%an|%ad|%ct",
            f"-n{limit}",
        ]
        if since:
            args.extend(["--since", since])

        rc, out, _ = await self._run(*args)
        if rc != 0:
            return []

        commits = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 5:
                commits.append(
                    GitCommit(
                        hash=parts[0],
                        short_hash=parts[1],
                        message=parts[2],
                        author=parts[3],
                        date=parts[4],
                        files_changed=0,
                    )
                )
        return commits

    async def commit(
        self,
        message: str,
        *,
        allow_empty: bool = False,
    ) -> str:
        """
        Stage all changes and commit with a structured message.

        Returns the commit hash on success, empty string on failure.
        """
        async with self._get_lock():
            gs = await self.status()
            if not gs.is_repo:
                logger.warning("[Git] Not a git repo — skipping commit")
                return ""
            if gs.clean:
                logger.debug("[Git] Nothing to commit — working tree clean")
                return ""

            paths = list(dict.fromkeys(gs.staged + gs.unstaged + gs.untracked))
            if paths:
                for i in range(0, len(paths), _MAX_STAGE_PATHS):
                    chunk = paths[i : i + _MAX_STAGE_PATHS]
                    rc_add, _, err_add = await self._run("add", "--", *chunk)
                    if rc_add != 0:
                        logger.warning(f"[Git] git add failed: {err_add}")
                        return ""

            commit_args = ["commit", "-m", _sanitize_git_message(message)]
            if allow_empty:
                commit_args.insert(1, "--allow-empty")
            rc, _, stderr = await self._run(*commit_args, env=self._author_env())
            if rc != 0:
                logger.warning(f"[Git] Commit failed: {stderr}")
                return ""

            rc, out, _ = await self._run("log", "-1", "--format=%H")
            if rc == 0:
                self._last_commit = out.splitlines()[0] if out else ""
                logger.info(f"[Git] Committed: {message[:60]} → {self._last_commit[:7]}")
                return self._last_commit
            return ""

    async def checkpoint(
        self,
        name: str,
        description: str = "",
        session_id: str = "",
    ) -> str:
        """
        Create a named checkpoint tag.

        This is the core of cross-session recovery: after completing a
        milestone, the agent calls checkpoint("feat-login") so a later
        session can revert to it if needed.

        Returns the checkpoint tag name.
        """
        async with self._get_lock():
            if not await self.is_repo():
                return ""

            commit_hash = self._last_commit
            if not commit_hash:
                rc, out, _ = await self._run("log", "-1", "--format=%H")
                if rc == 0 and out:
                    commit_hash = out.splitlines()[0]
                else:
                    logger.warning("[Git] No commits to checkpoint")
                    return ""

            tag_name = f"{_CHECKPOINT_PREFIX}{name}"
            rc_exist, _, _ = await self._run("rev-parse", f"refs/tags/{tag_name}")
            if rc_exist == 0:
                logger.warning(f"[Git] Checkpoint tag already exists: {tag_name}")
                return ""

            ts = datetime.now(UTC).isoformat()
            msg = _sanitize_git_message(
                f"Checkpoint: {name}\n\n{description}\n\nsession={session_id}\ncreated_at={ts}",
            )

            rc, _, stderr = await self._run("tag", "-a", tag_name, "-m", msg, commit_hash, env=self._author_env())
            if rc != 0:
                await self._run("tag", "-d", tag_name)
                rc2, _, _ = await self._run("tag", "-a", tag_name, "-m", msg, commit_hash, env=self._author_env())
                if rc2 != 0:
                    logger.warning(f"[Git] Failed to create checkpoint tag: {stderr}")
                    return ""

            logger.info(f"[Git] Checkpoint created: {tag_name} at {commit_hash[:7]}")
            return tag_name

    async def diff_unified(
        self,
        *,
        path: str = "",
        cached: bool = False,
        max_bytes: int = 200_000,
    ) -> str:
        """Return unified diff text (truncated). ``cached=True`` → ``git diff --cached``."""
        if not await self.is_repo():
            return "Not a git repository."
        args: list[str] = ["diff", "--no-color"]
        if cached:
            args.append("--cached")
        if path.strip():
            args.extend(["--", path.strip()])
        rc, stdout, stderr = await self._run(*args, timeout=60)
        if rc != 0 and not stdout.strip():
            return stderr or f"git diff failed (exit {rc})"
        body = stdout
        if len(body) > max_bytes:
            body = body[:max_bytes] + "\n… truncated"
        return body if body.strip() else "(no differences)"

    async def list_checkpoints(self) -> list[GitCheckpoint]:
        """List all agloom checkpoint tags."""
        if not await self.is_repo():
            return []

        rc, out, _ = await self._run(
            "for-each-ref",
            "--sort=-creatordate",
            "--format=%(refname:short)|%(objectname)|%(contents:subject)|%(creatordate:iso)",
            f"refs/tags/{_CHECKPOINT_PREFIX}*",
        )
        if rc != 0 or not out.strip():
            return []

        checkpoints = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                checkpoints.append(
                    GitCheckpoint(
                        name=parts[0].replace(_CHECKPOINT_PREFIX, ""),
                        commit_hash=parts[1],
                        description=parts[2],
                        created_at=parts[3],
                        session_id="",
                    )
                )
        return checkpoints

    async def get_revert_hint(self, n: int = 5) -> str:
        """
        Analyze recent commits and suggest whether to revert.

        Called when the agent detects the environment is in a broken state.
        Returns a suggestion like:
          "3 of the last 5 commits modified this area. Consider:
           git revert <hash>"

        Returns empty string if git is unavailable or no hint can be generated.
        """
        if not await self.is_repo():
            return ""

        commits = await self.log(limit=n)
        if not commits:
            return ""

        lines = [f"Last {len(commits)} commits:"]
        for c in commits:
            lines.append(f"  {c.short_hash} {c.date[:10]} — {c.message[:70]}")

        latest = commits[0]
        lines.append("")
        lines.append(f"Latest commit: {latest.short_hash}")
        lines.append(f"  git revert {latest.hash[:7]}  # undo last change")
        lines.append("  git log --oneline -10  # review full history")
        lines.append("  git diff HEAD~1  # see what changed in last commit")

        checkpoints = await self.list_checkpoints()
        if checkpoints:
            latest_cp = checkpoints[0]
            lines.append("")
            lines.append(f"Latest checkpoint: {latest_cp.name}")
            lines.append(f"  git checkout {latest_cp.commit_hash}  # restore checkpoint")

        return "\n".join(lines)

    async def get_session_summary(self) -> dict[str, Any]:
        """
        Build a structured summary of the current git state.
        Written to BootstrapState at session end.
        """
        gs = await self.status()
        commits = await self.log(limit=5)
        checkpoints = await self.list_checkpoints()

        return {
            "is_repo": gs.is_repo,
            "branch": gs.branch,
            "clean": gs.clean,
            "staged_files": len(gs.staged),
            "unstaged_files": len(gs.unstaged),
            "untracked_files": len(gs.untracked),
            "last_commit": commits[0].short_hash if commits else None,
            "recent_commits": [c.short_hash for c in commits[:5]],
            "checkpoints": [cp.name for cp in checkpoints],
            "commit_message_hint": commits[0].message if commits else "",
        }


#  Tool Factories


def git_status_tool(git_session: GitSession):
    async def git_status() -> str:
        """
        Run git status to see the current working tree state.
        Shows staged, unstaged, and untracked files.
        """
        gs = await git_session.status()
        if not gs.is_repo:
            return "Not a git repository. Skipping."

        lines = [f"On branch: {gs.branch}"]
        if gs.ahead or gs.behind:
            lines.append(f"Ahead: {gs.ahead}, Behind: {gs.behind}")

        if gs.clean:
            lines.append("Working tree clean — nothing to commit.")
        else:
            if gs.staged:
                lines.append(f"\nStaged ({len(gs.staged)}):")
                for f in gs.staged[:10]:
                    lines.append(f"  [staged] {f}")
            if gs.unstaged:
                lines.append(f"\nModified ({len(gs.unstaged)}):")
                for f in gs.unstaged[:10]:
                    lines.append(f"  [modified] {f}")
            if gs.untracked:
                lines.append(f"\nUntracked ({len(gs.untracked)}):")
                for f in gs.untracked[:10]:
                    lines.append(f"  [untracked] {f}")

        return "\n".join(lines)

    return git_status


def git_log_tool(git_session: GitSession):
    async def git_log(limit: int = 10) -> str:
        """
        Show recent git commits.

        Args:
            limit: Number of commits to show (default 10).
        """
        commits = await git_session.log(limit=limit)
        if not commits:
            return "No commits found."

        lines = [f"Last {len(commits)} commit(s):"]
        for c in commits:
            lines.append(f"  {c.short_hash} [{c.date[:10]}] {c.message}")
        return "\n".join(lines)

    return git_log


def git_commit_tool(git_session: GitSession):
    async def git_commit(message: str) -> str:
        """
        Stage all changes and commit with a descriptive message.

        Args:
            message: Commit message. Best practice: prefix with type.
                Examples:
                  "feat: implement user login — feat-001"
                  "fix: correct off-by-one in pagination — feat-003"
                  "chore: set up test infrastructure — infra-001"
        """
        if not message.strip():
            return "Error: commit message cannot be empty."

        gs = await git_session.status()
        if not gs.is_repo:
            return "Not a git repository. Cannot commit."
        if gs.clean:
            return "Working tree clean — nothing to commit."

        commit_hash = await git_session.commit(message)
        if commit_hash:
            return f"Committed: {commit_hash[:7]} — {message[:60]}"
        return "Commit failed. Check git status for details."

    return git_commit


def git_checkpoint_tool(git_session: GitSession, session_id: str = ""):
    async def git_checkpoint(name: str, description: str = "") -> str:
        """
        Create a named checkpoint. Use after completing a milestone
        so later sessions can recover to a known-good state.

        Args:
            name: Short checkpoint name (e.g. 'feat-login', 'infra-setup').
                  Avoid spaces — will be used as git tag prefix.
            description: What this checkpoint represents.
        """
        tag = await git_session.checkpoint(name, description, session_id)
        if tag:
            checkpoints = await git_session.list_checkpoints()
            latest = [c for c in checkpoints if c.name == name]
            if latest:
                cp = latest[0]
                return (
                    f"Checkpoint '{name}' created at {cp.commit_hash[:7]}. Restore with: git checkout {cp.commit_hash}"
                )
        return "Checkpoint creation failed (git may not be available)."

    return git_checkpoint


def git_diff_tool(git_session: GitSession):
    async def git_diff(path: str = "", cached: bool = False) -> str:
        """
        Show a unified diff for uncommitted changes.

        Args:
            path: Optional file path to limit the diff.
            cached: When True, show staged changes (``git diff --cached``).
        """
        return await git_session.diff_unified(path=path, cached=cached)

    return git_diff


def git_revert_hint_tool(git_session: GitSession):
    async def git_revert_hint() -> str:
        """
        Analyze recent commits and suggest whether to revert.
        Use when the codebase is in a broken state and you need to recover.
        """
        hint = await git_session.get_revert_hint()
        if hint:
            return hint
        return "No revert hint available (git may not be available)."

    return git_revert_hint
