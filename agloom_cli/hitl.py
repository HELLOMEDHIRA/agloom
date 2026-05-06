"""Human-in-the-loop approval handler for CLI (Cursor / Claude Code–style choices)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from agloom.hitl_contract import HITLEvent

from .hitl_allowlist import load_allowlist, merge_allowlist_file, resolve_allowlist_path

console = Console()

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


def _hitl_triple_choice(
    *,
    title: str,
    subtitle: str,
    detail: str,
    footer: str | None,
    row1: str,
    row2: str,
    row3: str,
    default: str = "2",
) -> str:
    """One Rich prompt for all HITL tri-state decisions. Returns ``accept``, ``reject``, or ``allowlist``."""
    body = (
        f"[bold yellow]{title}[/bold yellow]\n[dim]{subtitle}[/dim]\n\n{detail}"
        + (f"\n\n{footer}" if footer else "")
    )
    console.print()
    console.print(Panel(body, border_style="yellow"))
    console.print(
        f"  [green]1[/green] / [green]a[/green]  {row1}   "
        f"│   [red]2[/red] / [red]r[/red]  {row2}   "
        f"│   [cyan]3[/cyan] / [cyan]l[/cyan]  {row3}"
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
            "retry",
            "stop",
            "yes",
            "no",
        ],
        default=default,
    )
    c = choice.strip().lower()
    if c in ("2", "r", "reject", "stop", "no"):
        return "reject"
    if c in ("3", "l", "allowlist", "always", "trust"):
        return "allowlist"
    if c in ("1", "a", "accept", "y", "yes", "retry"):
        return "accept"
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
    """Build a ``user_callback`` for interactive terminals (Rich).

    For the **stable event names and return-value contract**, see
    ``agloom.hitl_contract`` / :class:`~agloom.hitl_contract.HITLEvent`.
    This function is **CLI-only**; library users should implement their own callback
    (web UI, tests, logging) using the same event strings.

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

        if event_type == HITLEvent.CLARIFICATION_REQUEST:
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

        if event_type == HITLEvent.TOOL_INTERRUPT_BEFORE:
            tool_name = _parse_tool_name(message)
            if not tool_name:
                console.print(f"[dim]{message}[/dim]")
                return "continue"

            if tool_name in runtime_tools:
                console.print(f"[green]✓ Allowlisted tool:[/green] {tool_name}")
                return "continue"

            choice = _hitl_triple_choice(
                title="Tool approval",
                subtitle=f"Tool: {tool_name}",
                detail=message,
                footer=f"[bold]Always allow[/bold] {persist_hint}",
                row1="Accept (this time only)",
                row2="Reject",
                row3="Always allow — [dim]saved to allowlist[/dim]",
                default="2",
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

        if event_type == HITLEvent.PATTERN_INTERRUPT:
            pattern = _parse_pattern_name(message)
            if pattern and pattern in runtime_patterns:
                console.print(f"[green]✓ Allowlisted pattern:[/green] {pattern}")
                return True

            if not pattern:
                console.print(f"[dim]{message}[/dim]")
                return True

            choice = _hitl_triple_choice(
                title="Pattern approval",
                subtitle=f"Pattern: {pattern}",
                detail=message[:2000],
                footer=f"[bold]Always allow this pattern[/bold] {persist_hint}",
                row1="Accept (this time only)",
                row2="Reject",
                row3="Always allow — [dim]saved to allowlist[/dim]",
                default="2",
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

        if event_type == HITLEvent.REACT_TOOL_USE_FAILED:
            choice = _hitl_triple_choice(
                title="Model turn rejected (tool_use_failed)",
                subtitle=(
                    "The API rejected the assistant message before any tool ran — "
                    "not the same gate as tool approval."
                ),
                detail=message[:3500],
                footer=None,
                row1="Retry (another model turn)",
                row2="Stop",
                row3="Retry — [dim]allowlist applies only after a real tool is proposed[/dim]",
                default="1",
            )
            if choice == "reject":
                return "abort"
            if choice == "allowlist":
                console.print(
                    "[dim]Always-allow lists gate real tool calls. Retrying with another model turn…[/dim]"
                )
            return "retry"

        if event_type == HITLEvent.WORKER_INTERRUPT_AFTER:
            # Informational only — the runtime ignores the return value.
            console.print()
            console.print(Panel(message, title="Worker completed", border_style="green"))
            return True

        if event_type == HITLEvent.WORKER_INTERRUPT_BEFORE:
            worker_id = _parse_worker_id(message)
            if worker_id and worker_id in runtime_workers:
                console.print(f"[green]✓ Allowlisted worker:[/green] {worker_id}")
                return "continue"

            if not worker_id:
                console.print(f"[dim]{message}[/dim]")
                return "continue"

            choice = _hitl_triple_choice(
                title="Worker approval",
                subtitle=f"Worker: {worker_id}",
                detail=message[:2000],
                footer=f"[bold]Always allow this worker[/bold] {persist_hint}",
                row1="Accept (this time only)",
                row2="Reject",
                row3="Always allow — [dim]saved to allowlist[/dim]",
                default="2",
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
