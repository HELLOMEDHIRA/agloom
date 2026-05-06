"""Human-in-the-loop approval handler for CLI (Cursor / Claude Code–style choices).

Triple gates (tool / pattern / worker / react recovery) use a structured
:class:`~agloom_cli.hitl_ask_types.AskUserRequest` (``ask_user``) with
``tool_call_id`` correlation for tool approval when the middleware supplies it.

The UI is pluggable via :func:`set_ui_providers` (``ask_user``, ``text_input``).
Default is Rich; the Textual TUI installs :class:`~agloom_cli.hitl_textual.AskUserScreen`
on mount.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from agloom.hitl_contract import HITLEvent
from agloom.logging_utils import get_logger

from .config import merge_tool_allowlist_into_session_json

_logger = get_logger("agloom_cli.hitl")
from .hitl_ask import build_hitl_triple_ask_request, new_hitl_tool_call_id, triple_answer_to_token
from .hitl_allowlist import load_allowlist, merge_allowlist_file, resolve_allowlist_path
from .hitl_ask_types import AskUserRequest, AskUserWidgetResult

console = Console()

TripleChoiceProvider = Callable[..., Awaitable[str]]
TextInputProvider = Callable[..., Awaitable[str]]
AskUserProvider = Callable[[AskUserRequest], Awaitable[AskUserWidgetResult]]

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


def _normalize_triple_choice(raw: str) -> str:
    """Map any accepted token (1/2/3, a/r/l, retry/stop, …) to ``accept``/``reject``/``allowlist``."""
    c = (raw or "").strip().lower()
    if c in ("2", "r", "reject", "stop", "no"):
        return "reject"
    if c in ("3", "l", "allowlist", "always", "trust"):
        return "allowlist"
    if c in ("1", "a", "accept", "y", "yes", "retry"):
        return "accept"
    return "reject"


async def _rich_triple_choice(
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
    """Default Rich-based tri-state prompt. Used by the plain CLI shell."""
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
            "1", "2", "3",
            "a", "r", "l",
            "accept", "reject", "allowlist",
            "retry", "stop", "yes", "no",
        ],
        default=default,
    )
    return _normalize_triple_choice(choice)


async def _rich_text_input(*, prompt: str, default: str = "") -> str:
    """Default Rich-based free-text prompt. Used for clarification answers."""
    return Prompt.ask(prompt, default=default)


def _format_hitl_triple_prompt(
    title: str,
    subtitle: str,
    detail: str,
    footer: str | None,
) -> str:
    parts = [title, subtitle, "", detail]
    if footer:
        parts.extend(["", footer])
    return "\n".join(parts)


async def _rich_ask_user(request: AskUserRequest) -> AskUserWidgetResult:
    """Rich console implementation of :class:`~agloom_cli.hitl_ask_types.AskUserRequest`."""
    answers: list[str] = []
    for q in request.get("questions") or []:
        qtype = q.get("type") or "text"
        qtext = q.get("question") or ""
        if qtype == "text":
            answers.append(await _text_input_provider(prompt=qtext, default=""))
            continue
        choices_list = q.get("choices") or []
        if not choices_list:
            answers.append(await _text_input_provider(prompt=qtext, default=""))
            continue
        lines = [f"[bold yellow]{qtext}[/bold yellow]", ""]
        prompt_choices: list[str] = []
        for i, ch in enumerate(choices_list, 1):
            val = (ch.get("value") or "").strip()
            lab = (ch.get("label") or val).strip() or val
            lines.append(f"  [green]{i}[/green]  {lab}")
            prompt_choices.append(str(i))
            if val:
                prompt_choices.append(val.lower())
        console.print()
        console.print(Panel("\n".join(lines), border_style="yellow"))
        default_key = (
            request.get("rich_prompt_default")
            if request.get("rich_prompt_default") in prompt_choices
            else ("2" if "2" in prompt_choices and len(choices_list) >= 2 else prompt_choices[0])
        )
        raw = Prompt.ask("Choice", choices=prompt_choices, default=default_key)
        rs = (raw or "").strip()
        if rs.isdigit():
            idx = int(rs) - 1
            if 0 <= idx < len(choices_list):
                answers.append((choices_list[idx].get("value") or "").strip().lower())
            else:
                answers.append("reject")
        else:
            answers.append(rs.lower())
    return {"type": "answered", "answers": answers}


_triple_choice_provider: TripleChoiceProvider = _rich_triple_choice
_text_input_provider: TextInputProvider = _rich_text_input
_ask_user_provider: AskUserProvider = _rich_ask_user


def set_ui_providers(
    *,
    triple_choice: TripleChoiceProvider | None = None,
    text_input: TextInputProvider | None = None,
    ask_user: AskUserProvider | None = None,
) -> None:
    """Swap HITL prompt UI (used by the Textual TUI to install modal-screen providers).

    HITL triple gates use the structured :class:`~agloom_cli.hitl_ask_types.AskUserRequest` path
    (``ask_user``). The legacy ``triple_choice`` provider is kept for compatibility but is no longer
    invoked by :func:`_hitl_triple_choice`.
    """
    global _triple_choice_provider, _text_input_provider, _ask_user_provider
    if triple_choice is not None:
        _triple_choice_provider = triple_choice
    if text_input is not None:
        _text_input_provider = text_input
    if ask_user is not None:
        _ask_user_provider = ask_user


def reset_ui_providers() -> None:
    """Restore the default Rich providers (call when the TUI exits)."""
    global _triple_choice_provider, _text_input_provider, _ask_user_provider
    _triple_choice_provider = _rich_triple_choice
    _text_input_provider = _rich_text_input
    _ask_user_provider = _rich_ask_user


async def _hitl_triple_choice(
    *,
    title: str,
    subtitle: str,
    detail: str,
    footer: str | None,
    row1: str,
    row2: str,
    row3: str,
    default: str = "2",
    tool_call_id: str = "",
) -> str:
    """Structured ask-user interrupt; returns ``accept``/``reject``/``allowlist``."""
    tcid = new_hitl_tool_call_id(tool_call_id)
    d = default if default in ("1", "2", "3") else "2"
    req = build_hitl_triple_ask_request(
        tool_call_id=tcid,
        prompt_text=_format_hitl_triple_prompt(title, subtitle, detail, footer),
        choice_labels=(row1, row2, row3),
        rich_prompt_default=d,
        focus_choice_index=int(d),
    )
    result = await _ask_user_provider(req)
    if result["type"] == "cancelled":
        return "reject"
    token = triple_answer_to_token(result["answers"])
    return _normalize_triple_choice(token)


async def _hitl_text_input(prompt: str, *, default: str = "") -> str:
    """Dispatch a free-text HITL prompt through the active provider."""
    return await _text_input_provider(prompt=prompt, default=default)


def create_user_callback(
    auto_approve_tools: list[str] | None = None,
    *,
    yaml_prefill_allow_tools: list[str] | None = None,
    persist_allowlist: bool = True,
    allowlist_path: Path | None = None,
    storage_root: Path | None = None,
    allowlist_strict_tools: bool = True,
    persist_allowlist_session_id: str | None = None,
):
    """Build a ``user_callback`` for interactive terminals (Rich).

    For the **stable event names and return-value contract**, see
    ``agloom.hitl_contract`` / :class:`~agloom.hitl_contract.HITLEvent`.
    This function is **CLI-only**; library users should implement their own callback
    (web UI, tests, logging) using the same event strings.

    Args:
        auto_approve_tools: Tool names never prompted (from config ``safety.auto_approve``) when not strict.
        yaml_prefill_allow_tools: Project + session ``safety.tool_allowlist`` (merged). Always unioned into
            the runtime allowlist first — honored even when *allowlist_strict_tools* and the JSON file exist.
        persist_allowlist: If True, "always allow" can append to the allowlist JSON under ``.agloom``.
        allowlist_path: Resolved path (use :func:`resolve_allowlist_path`); must stay under *storage_root*.
        storage_root: Active storage root (``storage_dir()``, i.e. project ``.agloom``). Used to validate *allowlist_path*.
        allowlist_strict_tools: If True (default), when the allowlist file exists, **only** its ``tools`` list
            applies; ``safety.auto_approve`` is ignored for tools. If False, yaml and JSON are unioned.
            If the file does not exist yet, ``auto_approve_tools`` is used alone.
        persist_allowlist_session_id: When set, "always allow" also appends to ``sessions/<id>.json``.
    """
    auto_tools = {t.strip() for t in (auto_approve_tools or []) if t.strip()}
    yaml_pre = {t.strip() for t in (yaml_prefill_allow_tools or []) if t.strip()}

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
        runtime_tools = yaml_pre | set(file_tools)
    else:
        runtime_tools = yaml_pre | set(auto_tools) | set(file_tools)
    runtime_patterns = set(file_patterns)
    runtime_workers = set(file_workers)

    _hint_parts: list[str] = []
    if persist_allowlist_session_id:
        sid = persist_allowlist_session_id.strip()
        disp = f"{sid[:8]}…" if len(sid) > 8 else sid
        _hint_parts.append(f"session [cyan]{disp}[/cyan].json")
    if persist_allowlist and path:
        _hint_parts.append(f"[cyan]{path.name}[/cyan]")
    if _hint_parts:
        persist_hint = "(writes to " + " + ".join(_hint_parts) + ")"
    else:
        persist_hint = "(this session only — persistence off)"

    async def callback(event_type: str, message: str | dict) -> Any:
        nonlocal runtime_tools, runtime_patterns, runtime_workers

        if event_type == HITLEvent.CLARIFICATION_REQUEST:
            if isinstance(message, dict):
                q = str(message.get("question", ""))
                wid = message.get("worker_id", "")
                ask_label = f"Worker {wid} asks: {q}" if wid else q or "Clarification needed"
            else:
                ask_label = f"Clarification: {message}"
            return await _hitl_text_input(ask_label, default="")

        if event_type == HITLEvent.TOOL_INTERRUPT_BEFORE:
            tool_call_id = ""
            if isinstance(message, dict):
                tool_name = str(message.get("tool_name") or "").strip()
                if not tool_name:
                    tool_name = _parse_tool_name(str(message.get("detail") or "")) or ""
                tool_call_id = str(message.get("tool_call_id") or "")
                detail = str(message.get("detail") or message)
            elif isinstance(message, str):
                tool_name = _parse_tool_name(message) or ""
                detail = message
            else:
                console.print(f"[dim]{message!r}[/dim]")
                return "continue"

            if not tool_name:
                console.print(f"[dim]{detail}[/dim]")
                return "continue"

            if tool_name in runtime_tools:
                _logger.event(
                    f"[HITL] Skipping approval UI for {tool_name!r} (allowlisted via safety.auto_approve, "
                    "safety.tool_allowlist, and/or saved allowlist). Remove it there to get the prompt."
                )
                return "continue"

            choice = await _hitl_triple_choice(
                title="Tool approval",
                subtitle=f"Tool: {tool_name}",
                detail=detail,
                footer=f"[bold]Always allow[/bold] {persist_hint}",
                row1="Accept (this time only)",
                row2="Reject",
                row3="Always allow — [dim]saved to session JSON / allowlist[/dim]",
                default="2",
                tool_call_id=tool_call_id,
            )
            if choice == "reject":
                return "abort"
            if choice == "allowlist":
                runtime_tools.add(tool_name)
                wrote = False
                if persist_allowlist_session_id:
                    merge_tool_allowlist_into_session_json(persist_allowlist_session_id, tool_name)
                    console.print(f"[cyan]Saved '{tool_name}' to session JSON (safety.tool_allowlist).[/cyan]")
                    wrote = True
                if persist_allowlist and path is not None:
                    merge_allowlist_file(path, tools=[tool_name])
                    if not wrote:
                        console.print(f"[cyan]Saved '{tool_name}' to {path.name}.[/cyan]")
                elif not wrote:
                    console.print("[cyan]Allowlisted for this CLI run (not saved).[/cyan]")
            return "continue"

        if not isinstance(message, str):
            return True

        if event_type == HITLEvent.PATTERN_INTERRUPT:
            pattern = _parse_pattern_name(message)
            if pattern and pattern in runtime_patterns:
                console.print(f"[green]✓ Allowlisted pattern:[/green] {pattern}")
                return True

            if not pattern:
                console.print(f"[dim]{message}[/dim]")
                return True

            choice = await _hitl_triple_choice(
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
            choice = await _hitl_triple_choice(
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

            choice = await _hitl_triple_choice(
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
