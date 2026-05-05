"""Human-in-the-loop approval handler for CLI (Cursor / Claude Code–style choices)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .hitl_allowlist import load_allowlist, merge_allowlist_file, resolve_allowlist_path

console = Console()


SENSITIVE_TOOLS = {
    "run_shell": "execute shell commands",
    "run_shell_interactive": "execute interactive shell commands",
    "remove_file": "delete files",
    "write_file": "write/overwrite files",
    "set_working_directory": "change working directory",
    "copy_file": "copy files/directories",
    "move_file": "move files/directories",
    "http_request": "make HTTP requests",
    "http_post": "POST requests",
    "http_put": "PUT requests",
    "http_delete": "DELETE requests",
}

_TOOL_LINE_RE = re.compile(r"Tool\s*:\s*(\S+)", re.IGNORECASE)
_WORKER_LINE_RE = re.compile(r"Worker\s*:\s*(\S+)", re.IGNORECASE)
_PATTERN_BRACKET_RE = re.compile(r"\[([A-Za-z0-9_]+)\]")


def _parse_tool_name(message: str) -> str | None:
    m = _TOOL_LINE_RE.search(message)
    return m.group(1).strip() if m else None


def _parse_worker_id(message: str) -> str | None:
    m = _WORKER_LINE_RE.search(message)
    return m.group(1).strip() if m else None


def _parse_pattern_name(message: str) -> str | None:
    # e.g. "MyAgent INTERRUPT-BEFORE [REACT]\nQuery: ..."
    matches = _PATTERN_BRACKET_RE.findall(message)
    if not matches:
        return None
    # Prefer token that looks like a pattern name (uppercase short)
    for tok in matches:
        if tok.isupper() or tok in ("REACT", "DIRECT", "SUPERVISOR", "PIPELINE", "SWARM", "HYBRID_DAG"):
            return tok
    return matches[0]


def _hitl_choice_prompt(
    *,
    title: str,
    subtitle: str,
    detail: str,
    allowlist_label: str,
    persist_hint: str,
) -> str:
    """Return 'accept', 'reject', or 'allowlist'."""
    console.print()
    console.print(
        Panel(
            f"[bold yellow]{title}[/bold yellow]\n[dim]{subtitle}[/dim]\n\n{detail}\n\n"
            f"[bold]{allowlist_label}[/bold] {persist_hint}",
            border_style="yellow",
        )
    )
    console.print(
        "  [green]1[/green] / [green]a[/green]  Accept (this time only)   "
        "│   [red]2[/red] / [red]r[/red]  Reject   "
        "│   [cyan]3[/cyan] / [cyan]l[/cyan]  Always allow — [dim]saved to allowlist[/dim]"
    )
    console.print()
    choice = Prompt.ask(
        "Choice",
        choices=[
            "1",
            "2",
            "3",
            "a",
            "r",
            "l",
            "accept",
            "reject",
            "allowlist",
        ],
        default="2",
    )
    c = choice.strip().lower()
    if c in ("1", "a", "accept", "y", "yes"):
        return "accept"
    if c in ("3", "l", "allowlist", "always", "trust"):
        return "allowlist"
    return "reject"


def create_user_callback(
    auto_approve_tools: list[str] | None = None,
    require_all: bool = False,
    *,
    persist_allowlist: bool = True,
    allowlist_path: Path | None = None,
    storage_root: Path | None = None,
    allowlist_strict_tools: bool = True,
):
    """Create ``user_callback`` for agloom HITL (L1/L2/L3).

    **L2 tool interrupts** use event ``tool_interrupt_before`` (see ``HumanApprovalMiddleware``).
    Choices match common assistant UX: accept once, reject, or always allow (persisted allowlist).

    Args:
        auto_approve_tools: Tool names never prompted (from config ``safety.auto_approve``) when not strict.
        require_all: Reserved for future use.
        persist_allowlist: If True, "always allow" appends to the allowlist JSON under ``.agloom``.
        allowlist_path: Resolved path (use :func:`resolve_allowlist_path`); must stay under *storage_root*.
        storage_root: Active storage root (``storage_dir()``, i.e. project ``.agloom``). Used to validate *allowlist_path*.
        allowlist_strict_tools: If True (default), when the allowlist file exists, **only** its ``tools`` list
            applies; ``safety.auto_approve`` is ignored for tools. If False, yaml and JSON are unioned.
            If the file does not exist yet, ``auto_approve_tools`` is used alone.
    """
    _ = require_all
    auto_tools = {t.strip() for t in (auto_approve_tools or []) if t.strip()}

    path: Path | None = allowlist_path
    if path is None and storage_root is not None:
        path = resolve_allowlist_path(storage_root, None)
    if path is not None and storage_root is not None:
        root = storage_root.resolve()
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"allowlist_path {path} must be under storage root {root}")

    file_tools: set[str] = set()
    file_patterns: set[str] = set()
    file_workers: set[str] = set()
    if path is not None and path.exists():
        data = load_allowlist(path)
        file_tools = set(data.get("tools", []))
        file_patterns = set(data.get("patterns", []))
        file_workers = set(data.get("workers", []))
        file_exists = True
    else:
        file_exists = False

    if allowlist_strict_tools and file_exists:
        runtime_tools = set(file_tools)
    else:
        runtime_tools = set(auto_tools) | set(file_tools)
    runtime_patterns = set(file_patterns)
    runtime_workers = set(file_workers)

    persist_hint = (
        f"(writes to [cyan]{path}[/cyan])" if persist_allowlist and path else "(this session only — persistence off)"
    )

    async def callback(event_type: str, message: str | dict) -> Any:
        nonlocal runtime_tools, runtime_patterns, runtime_workers

        if event_type == "clarification_request":
            if isinstance(message, dict):
                q = str(message.get("question", ""))
                wid = message.get("worker_id", "")
                console.print(f"[bold]Worker {wid} asks:[/bold] {q}")
            else:
                console.print(f"[bold]Clarification:[/bold] {message}")
            ans = Prompt.ask("Your answer", default="")
            return ans

        if not isinstance(message, str):
            return True

        if event_type == "tool_interrupt_before":
            tool_name = _parse_tool_name(message)
            if not tool_name:
                console.print(f"[dim]{message}[/dim]")
                return "continue"

            if tool_name in runtime_tools:
                console.print(f"[green]✓ Allowlisted tool:[/green] {tool_name}")
                return "continue"

            description = SENSITIVE_TOOLS.get(tool_name, f"execute {tool_name}")
            choice = _hitl_choice_prompt(
                title="Tool approval",
                subtitle=f"Tool: {tool_name}",
                detail=message,
                allowlist_label="Always allow",
                persist_hint=persist_hint,
            )
            if choice == "reject":
                return "abort"
            if choice == "allowlist":
                runtime_tools.add(tool_name)
                if persist_allowlist and path is not None:
                    merge_allowlist_file(path, tools=[tool_name])
                    console.print(f"[cyan]Saved '{tool_name}' to tool allowlist.[/cyan]")
                else:
                    console.print("[cyan]Allowlisted for this CLI run (not saved).[/cyan]")
            return "continue"

        if event_type == "pattern_interrupt":
            pattern = _parse_pattern_name(message)
            if pattern and pattern in runtime_patterns:
                console.print(f"[green]✓ Allowlisted pattern:[/green] {pattern}")
                return True

            if not pattern:
                console.print(f"[dim]{message}[/dim]")
                return True

            choice = _hitl_choice_prompt(
                title="Pattern approval",
                subtitle=f"Pattern: {pattern}",
                detail=message[:2000],
                allowlist_label="Always allow this pattern",
                persist_hint=persist_hint,
            )
            if choice == "reject":
                return "no"
            if choice == "allowlist":
                runtime_patterns.add(pattern)
                if persist_allowlist and path is not None:
                    merge_allowlist_file(path, patterns=[pattern])
                    console.print(f"[cyan]Saved pattern '{pattern}' to allowlist.[/cyan]")
                else:
                    console.print("[cyan]Allowlisted for this CLI run (not saved).[/cyan]")
            return True

        if event_type == "worker_interrupt_before":
            worker_id = _parse_worker_id(message)
            if worker_id and worker_id in runtime_workers:
                console.print(f"[green]✓ Allowlisted worker:[/green] {worker_id}")
                return "continue"

            if not worker_id:
                console.print(f"[dim]{message}[/dim]")
                return "continue"

            choice = _hitl_choice_prompt(
                title="Worker approval",
                subtitle=f"Worker: {worker_id}",
                detail=message[:2000],
                allowlist_label="Always allow this worker",
                persist_hint=persist_hint,
            )
            if choice == "reject":
                return "skip"
            if choice == "allowlist":
                runtime_workers.add(worker_id)
                if persist_allowlist and path is not None:
                    merge_allowlist_file(path, workers=[worker_id])
                    console.print(f"[cyan]Saved worker '{worker_id}' to allowlist.[/cyan]")
                else:
                    console.print("[cyan]Allowlisted for this CLI run (not saved).[/cyan]")
            return "continue"

        # Unknown event: fail-open
        console.print(f"[dim]{message}[/dim]")
        return True

    return callback
