"""Interactive REPL shell — Deep Agents / Claude Code style rich UI.

**Thinking** in the UI is **not** Python logging. It is the live **AgentEvent** stream from
``astream_events`` (classify / pattern / tool_start / tool_end / tokens, etc.) — the same
class of signal a product shell would show as “reasoning” or tool activity.

**Framework** INFO/DEBUG (HTTP, Groq SDK, SQLite drivers, LangGraph store, …) stays **off** the
console below WARNING for the whole CLI run (including ``--verbose``). **``agloom.*``** INFO/DEBUG
is hidden by default and shown when ``--verbose`` — see ``agloom_cli.quiet_logs``.
"""

from __future__ import annotations

import asyncio
import os
import sys

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import add_to_session_history
from .session_resume import (
    hydrate_repl_history_from_agent_memory,
    hydrate_repl_history_from_session_json,
)
from .ui import RichUI, get_ui, reset_ui

console = Console()

_THINKING_SCROLL_LINES = 16
# Reasoning panel: Cursor / Claude Code–style single surface (one Live region, no stacked borders).
_LIVE_REFRESH_HZ = 12
# Side card width: readable on narrow terminals; scales slightly with console width.
_SESSION_CARD_MIN_W = 34
_SESSION_CARD_MAX_W = 46

# Textual “glass” preset: rounded boxes, muted borders (easier on the eyes than neon panels).
_SOFT_BOX = box.ROUNDED
_SOFT_BORDER_SESSION = "rgb(92,118,148)"
_SOFT_BORDER_LIVE = "rgb(88,128,158)"
_SOFT_BORDER_USER = "rgb(130,105,145)"
_SOFT_BORDER_ANSWER = "rgb(95,145,125)"
_SOFT_BORDER_META = "rgb(85,110,135)"
_SOFT_BORDER_OK = "rgb(100,140,115)"
_SOFT_BORDER_HELP = "rgb(95,125,155)"
_SOFT_BORDER_WARN = "rgb(155,135,95)"


def _ellipsize_middle(path: str, max_len: int = 42) -> str:
    """Shorten long paths for the session card (prefer keeping head and tail)."""
    if len(path) <= max_len:
        return path
    head = max_len // 2 - 1
    tail = max_len - head - 1
    return f"{path[:head]}…{path[-tail:]}"


def _session_side_card(
    *,
    session_id_full: str,
    turns: int,
    tokens_est: int,
    model: str,
    tools_count: int | None,
    cwd: str,
    langsmith_on: bool,
    card_width: int,
    tui_soft: bool = False,
) -> Panel:
    """Right-column session summary (tokens, turns, id, model) — printed at shell start."""
    sid_short = session_id_full[:8] if len(session_id_full) >= 8 else session_id_full
    tbl = Table(show_header=False, box=None, pad_edge=False, collapse_padding=True)
    tbl.add_column("k", style="dim", justify="right", width=10, no_wrap=True)
    tbl.add_column("v", overflow="fold")

    sid_style = "bold #b8d4f0" if tui_soft else "bold bright_cyan"
    model_style = "italic #a8c8e0" if tui_soft else "cyan"
    tbl.add_row("Session", Text(sid_short, style=sid_style))
    if len(session_id_full) > len(sid_short):
        tbl.add_row("", Text(session_id_full, style="dim"))
    tbl.add_row("Turns", str(turns))
    tbl.add_row("Tokens", Text.assemble((f"{tokens_est:,}", "bold"), ("  ≈ est.", "dim")))
    tbl.add_row("Model", Text(_ellipsize_middle(model, card_width - 2), style=model_style))
    if tools_count is not None:
        tbl.add_row("Tools", str(tools_count))
    tbl.add_row("CWD", Text(_ellipsize_middle(cwd.replace("\\", "/"), card_width + 8), style="dim"))

    trace_st = "italic #8fb89a" if tui_soft else "green"
    trace = Text("✓ ", style=trace_st) if langsmith_on else Text("○ ", style="dim")
    trace.append("LangSmith", style="dim")
    body = Group(tbl, Text(""), trace)

    title = "[italic #c5d8ec]Session[/italic #c5d8ec]" if tui_soft else "[bold white]Session[/bold white]"
    bstyle = _SOFT_BORDER_SESSION if tui_soft else "bright_blue"
    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=bstyle,
        box=_SOFT_BOX if tui_soft else box.SQUARE,
        width=card_width,
        padding=(0, 1),
    )


def _print_startup_panels(left: Panel, right: Panel) -> None:
    """STATUS (left) + Session card (right); stack when the terminal is too narrow."""
    term_w = console.width or 80
    if term_w >= 86:
        console.print(
            Columns(
                [left, right],
                equal=False,
                expand=True,
                padding=(0, 1),
            )
        )
    else:
        console.print(left)
        console.print(right)


def tui_soft_user_message(message: str) -> Panel:
    """Rounded user bubble for the Textual transcript (plain text safe)."""
    body = Text("› ", style="bold #d4c0e4")
    body.append(message, style="#e8ecf4")
    return Panel(
        body,
        title="[italic dim #8f8498]You[/]",
        title_align="left",
        border_style=_SOFT_BORDER_USER,
        box=_SOFT_BOX,
        padding=(0, 1),
    )


def tui_soft_answer(text: str) -> Panel:
    return Panel(
        text,
        title="[italic #a8d4c0]Answer[/]",
        title_align="left",
        border_style=_SOFT_BORDER_ANSWER,
        box=_SOFT_BOX,
        padding=(0, 1),
    )


def tui_soft_status_banner(welcome: str) -> Panel:
    return Panel(
        f"[#8fb89a]✓[/] [#d0dae8]{welcome}[/]\n"
        "[dim #7a8899]Scroll the chat on the left — session glass card on the right.[/]",
        title="[italic #a8c0d8]Ready[/]",
        border_style=_SOFT_BORDER_OK,
        box=_SOFT_BOX,
        padding=(0, 1),
    )


def tui_soft_done_banner(turns: int) -> Panel:
    return Panel(
        f"[#8fb89a]✓[/] [dim]Completed · {turns} turn(s)[/]",
        border_style=_SOFT_BORDER_OK,
        box=_SOFT_BOX,
        padding=(0, 1),
    )


def tui_soft_help_panel() -> Panel:
    return Panel(
        "[#b8c8e0]Commands:[/] exit · clear · history · help · thinking (toggle)\n"
        "[#b8c8e0]Keys:[/] [dim]ctrl+shift+q[/] or [dim]F10[/] exit (VS Code terminal)\n"
        "[#b8c8e0]Env:[/] AGLOOM_EXPAND_THINKING=0 compact reasoning",
        title="[italic #a8c0e0]Help[/]",
        border_style=_SOFT_BORDER_HELP,
        box=_SOFT_BOX,
        padding=(0, 1),
    )


def tui_soft_warn_banner(text: str) -> Panel:
    return Panel(
        Text(text, style="#d8c8a0"),
        border_style=_SOFT_BORDER_WARN,
        box=_SOFT_BOX,
        padding=(0, 1),
        title="[dim italic]Notice[/]",
    )


def _session_info_strip(
    *,
    working_dir: str,
    status_model: str,
    turns: int,
    tokens_est: int,
) -> Panel:
    """Footer strip after each turn — cumulative tokens and turn count."""
    return Panel(
        f"[green]●[/green] [green]session[/green]  "
        f"[dim]turns[/dim] [cyan]{turns}[/cyan]  "
        f"[dim]tokens[/dim] [cyan]{tokens_est:,}[/cyan] [dim]≈[/dim]  "
        f"[dim]{_ellipsize_middle(working_dir, 36)}[/dim]  "
        f"[cyan]{status_model}[/cyan]",
        border_style="dim",
        padding=(0, 1),
        title="[dim]INFO[/dim]",
    )


def _default_expand_thinking() -> bool:
    """Show full reasoning after each reply by default (no env needed).

    Set ``AGLOOM_EXPAND_THINKING=0`` (or ``false`` / ``off``) for a compact summary by default
    (e.g. scripts or narrow terminals).
    """
    v = os.environ.get("AGLOOM_EXPAND_THINKING", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    return True


def _append_trace_line(thinking_lines: list[str], event_type: str, data: dict) -> None:
    """Append one line from the **agent event stream** (not from stdlib logging)."""
    if event_type == "thinking":
        name = (data.get("name") or "classify").strip() or "classify"
        out = data.get("output", "")
        s = str(out).strip() if out else ""
        if len(s) > 360:
            s = s[:360] + "…"
        thinking_lines.append(f"• {name}: {s}" if s else f"• {name}")
    elif event_type == "llm_call":
        name = (data.get("name") or "llm").strip() or "llm"
        dur = data.get("duration_ms")
        thinking_lines.append(f"• {name} ({dur} ms)" if dur is not None else f"• {name}")
    elif event_type == "worker_start":
        thinking_lines.append(f"• worker → {data.get('name', '')}")
    elif event_type == "worker_end":
        thinking_lines.append(f"• worker ✓ {data.get('name', '')}")
    elif event_type == "cache_hit":
        thinking_lines.append("• cache hit")
    elif event_type == "reflection":
        thinking_lines.append("• reflection")
    elif event_type == "fallback":
        o = data.get("output", "")
        thinking_lines.append(f"• fallback: {str(o)[:200]}")


def _thinking_body_text(lines: list[str]) -> Text:
    """Merge trace lines; lines may contain Rich markup (tool highlights)."""
    if not lines:
        return Text("…", style="italic dim")
    chunk = lines[-_THINKING_SCROLL_LINES:]
    body = Text()
    for i, raw in enumerate(chunk):
        if i:
            body.append("\n")
        try:
            body.append_text(Text.from_markup(raw))
        except Exception:
            body.append(raw)
    return body


def _live_agent_panel(thinking_lines: list[str], stream: Text, *, tui_soft: bool = False) -> Panel:
    """One bordered region: reasoning (spinner until first step) + optional streaming answer."""
    n = len(thinking_lines)
    extra = n - min(n, _THINKING_SCROLL_LINES)
    subtitle = f"[dim]{n} step(s)[/dim]" + (f" · [dim]↑ {extra} earlier[/dim]" if extra > 0 else "")

    inner: list = []
    if not thinking_lines and not stream.plain:
        spin_style = "italic rgb(140,170,200)" if tui_soft else "bold dim cyan"
        inner.append(
            Align.left(Spinner("dots2", text="Reasoning", style=spin_style)),
        )
    else:
        hdr_style = "bold italic #9ec5e0" if tui_soft else "bold dim cyan"
        inner.append(Text("Reasoning", style=hdr_style))
        inner.append(Text("\n"))
        inner.append(_thinking_body_text(thinking_lines))

    if stream.plain:
        inner.append(Text("\n"))
        w = console.width or 80
        rule_style = "dim #4a5a6e" if tui_soft else "dim"
        inner.append(Text("─" * max(12, min(w - 4, 56)), style=rule_style))
        inner.append(Text("\n"))
        ans_style = "bold #a8d4b4" if tui_soft else "bold green"
        inner.append(Text("Answer", style=ans_style))
        inner.append(Text("\n"))
        inner.append(stream)

    title = (
        "[dim]#5a6d82━━[/] [#c5d8ec]agloom[/] [dim]#5a6d82━━[/]"
        if tui_soft
        else "[dim]━━[/dim] [bold white]agloom[/bold white] [dim]━━[/dim]"
    )
    bstyle = _SOFT_BORDER_LIVE if tui_soft else "cyan"
    return Panel(
        Group(*inner),
        title=title,
        subtitle=subtitle,
        subtitle_align="right",
        border_style=bstyle,
        box=_SOFT_BOX if tui_soft else box.SQUARE,
        padding=(0, 1),
    )


def _thinking_footer_panel(
    thinking_lines: list[str], *, expanded: bool, tui_soft: bool = False
) -> Panel | None:
    """After a turn: compact or full reasoning as a Rich panel (for console or Textual)."""
    if not thinking_lines:
        return None
    if expanded:
        try:
            body = Text()
            for i, raw in enumerate(thinking_lines):
                if i:
                    body.append("\n")
                body.append_text(Text.from_markup(raw))
        except Exception:
            body = Text("\n".join(thinking_lines))
        title = (
            "[italic #b0c8e0]Reasoning[/] [dim](full)[/dim]"
            if tui_soft
            else "[bold dim]Reasoning[/bold dim] [cyan](full)[/cyan]"
        )
        bstyle = _SOFT_BORDER_LIVE if tui_soft else "dim cyan"
        return Panel(
            body,
            title=title,
            border_style=bstyle,
            box=_SOFT_BOX if tui_soft else box.SQUARE,
            padding=(0, 1),
        )
    last = thinking_lines[-1]
    preview = last if len(last) <= 88 else last[:88] + "…"
    try:
        preview_text = Text.from_markup(preview)
    except Exception:
        preview_text = Text(preview)
    summary = Text()
    summary.append("▸ ", style="dim")
    rstyle = "bold italic #8a9cad" if tui_soft else "bold dim"
    summary.append("Reasoning", style=rstyle)
    summary.append(f" · {len(thinking_lines)} step", style="dim")
    if len(thinking_lines) != 1:
        summary.append("s", style="dim")
    summary.append("\n", style="dim")
    summary.append_text(preview_text)
    summary.append("\n", style="dim")
    summary.append_text(
        Text.from_markup(
            "[dim]Tip:[/dim] [#9ec5e0]thinking[/] "
            "[dim]· compact vs full on later turns[/dim]"
            if tui_soft
            else "[dim]Tip:[/dim] [cyan]thinking[/cyan] [dim]· compact vs full on later turns[/dim]"
        )
    )
    bstyle = _SOFT_BORDER_META if tui_soft else "dim"
    return Panel(
        summary,
        border_style=bstyle,
        box=_SOFT_BOX if tui_soft else box.SQUARE,
        padding=(0, 1),
    )


def _print_thinking_footer(thinking_lines: list[str], *, expanded: bool) -> None:
    """After a turn: one summary strip (collapsed) or full reasoning (expanded)."""
    p = _thinking_footer_panel(thinking_lines, expanded=expanded, tui_soft=False)
    if p is not None:
        console.print(p)


def _use_textual_repl() -> bool:
    """Use Textual split layout (scrollable chat + fixed session card) when stdin/stdout are TTY.

    Non-TTY runs (CI, piped IO, redirected stdin/stdout) automatically fall back to the
    Rich line shell. No env-var override needed — HITL prompts work in both modes.
    """
    try:
        stdin_ok = bool(getattr(sys.stdin, "isatty", lambda: False)())
        stdout_ok = bool(getattr(sys.stdout, "isatty", lambda: False)())
    except Exception:
        return False
    return stdin_ok and stdout_ok


def render_banner(text: str = "AGLOOM") -> Panel:
    """Render text as ASCII art using pyfiglet with rich styling."""
    font = "small"
    try:
        import pyfiglet  # type: ignore[import-not-found]

        fig = pyfiglet.Figlet(font=font, width=120)
        ascii_art = fig.renderText(text)
    except Exception:
        ascii_art = text

    t = Text(ascii_art, style="bold cyan")

    return Panel.fit(
        t,
        border_style="cyan",
        padding=(0, 1),
        subtitle=f"[cyan]v{__version__}[/cyan]",
        subtitle_align="right",
    )


class ShellState:
    """Manages shell state across sessions."""

    def __init__(self):
        self.history: list[tuple[str, str]] = []
        self.session_id: str | None = None
        self.total_tokens_est: int = 0
        self.ui: RichUI = get_ui(console)
        self.expand_thinking: bool = _default_expand_thinking()

    def add_turn(self, query: str, output: str) -> None:
        self.history.append((query, output))
        self.total_tokens_est += max(0, len(query) + len(output)) // 4
        self.ui.token_count = self.total_tokens_est
        self.ui.add_to_history(query, output)

    def get_history(self) -> list[tuple[str, str]]:
        return self.history


async def run_shell(
    agent,
    *,
    welcome: str = "Ready to code!",
    verbose: bool = False,
    llm_status: str | None = None,
    thread_id: str | None = None,
    tools_count: int | None = None,
) -> None:
    """Interactive shell: Textual split view (scrollable chat + fixed session card) when possible."""
    if _use_textual_repl():
        try:
            from .repl_tui import run_shell_tui
        except ImportError:
            pass
        else:
            await run_shell_tui(
                agent,
                welcome=welcome,
                verbose=verbose,
                llm_status=llm_status,
                thread_id=thread_id,
                tools_count=tools_count,
            )
            return
    await run_shell_plain(
        agent,
        welcome=welcome,
        verbose=verbose,
        llm_status=llm_status,
        thread_id=thread_id,
        tools_count=tools_count,
    )


async def run_shell_plain(
    agent,
    *,
    welcome: str = "Ready to code!",
    verbose: bool = False,
    llm_status: str | None = None,
    thread_id: str | None = None,
    tools_count: int | None = None,
) -> None:
    """Rich line-based shell (used when stdin/stdout are non-TTY or Textual isn't installed).

    Features:
    - Status bar with LangSmith (banner printed by CLI before ``run_shell``)
    - Chat-style message display
    - Rich thinking indicator and tool visualization
    """
    reset_ui()
    state = ShellState()

    working_dir = os.getcwd()
    state.ui.working_dir = working_dir
    state.ui.langsmith_enabled = bool(os.environ.get("LANGCHAIN_TRACING_V2"))

    invoke_tid = thread_id or state.ui.thread_id
    state.ui.thread_id = invoke_tid[:8] if len(invoke_tid) > 8 else invoke_tid

    # Prefer SessionMemory (SQLite graph store); fall back to sessions/*.json messages.
    if not await hydrate_repl_history_from_agent_memory(agent, invoke_tid, state):
        hydrate_repl_history_from_session_json(invoke_tid, state)

    langsmith_status = (
        "[bold green]✓[/bold green] [dim]LangSmith: enabled (agloom-cli)[/dim]"
        if state.ui.langsmith_enabled
        else "[dim]○ LangSmith: disabled[/dim]"
    )

    status_model = llm_status or "auto:auto"
    term_w = console.width or 80
    card_w = min(
        _SESSION_CARD_MAX_W,
        max(_SESSION_CARD_MIN_W, min(_SESSION_CARD_MAX_W, term_w // 3 + 8)),
    )

    left_status = Panel(
        f"{langsmith_status}\n"
        f"[bold green]✓[/bold green] [bold green]{welcome}[/bold green]\n"
        f"[dim]Session details →[/dim]",
        border_style="green",
        padding=(0, 2),
        title="[bold]STATUS[/bold]",
    )
    right_card = _session_side_card(
        session_id_full=invoke_tid,
        turns=len(state.history),
        tokens_est=state.total_tokens_est,
        model=status_model,
        tools_count=tools_count,
        cwd=working_dir,
        langsmith_on=state.ui.langsmith_enabled,
        card_width=card_w,
    )
    _print_startup_panels(left_status, right_card)
    console.print()

    console.print(
        _session_info_strip(
            working_dir=working_dir,
            status_model=status_model,
            turns=len(state.history),
            tokens_est=state.total_tokens_est,
        )
    )
    console.print()

    while True:
        try:
            prompt_text = Prompt.ask(
                "[bold cyan]❯[/bold cyan] ",
                default="",
                show_default=False,
            )

            if not prompt_text.strip():
                continue

            if prompt_text.strip().lower() in ("exit", "quit", "q"):
                console.print("\n[dim]Goodbye! 👋[/dim]")
                break

            if prompt_text.strip().lower() == "clear":
                console.clear()
                console.print("[dim]Shell cleared.[/dim]\n")
                continue

            if prompt_text.strip().lower() == "history":
                if state.history:
                    console.print()
                    for i, (q, a) in enumerate(state.history, 1):
                        console.print(f"[dim]{i}.[/dim] [magenta]>{q}[/magenta]")
                        console.print(f"   {a[:100]}...")
                    console.print()
                else:
                    console.print("[dim]No history yet.[/dim]")
                continue

            if prompt_text.strip().lower() == "help":
                _show_help()
                continue

            pt_lower = prompt_text.strip().lower()
            if pt_lower in ("thinking", "thinking toggle"):
                state.expand_thinking = not state.expand_thinking
                mode = "expanded (full trace after each reply)" if state.expand_thinking else "collapsed (summary only)"
                console.print(f"[dim]Thinking display:[/dim] [cyan]{mode}[/cyan]")
                continue
            if pt_lower == "thinking on":
                state.expand_thinking = True
                console.print("[dim]Thinking display:[/dim] [cyan]expanded[/cyan]")
                continue
            if pt_lower == "thinking off":
                state.expand_thinking = False
                console.print("[dim]Thinking display:[/dim] [cyan]collapsed[/cyan]")
                continue

            console.print()
            console.print(
                Panel(
                    f"[bold magenta]>[/bold magenta] {prompt_text}",
                    border_style="magenta",
                    padding=(0, 1),
                )
            )
            console.print()

            thinking_lines: list[str] = []
            tool_status: dict = {}
            stream_text = Text()

            if not hasattr(agent, "astream_events"):
                if not hasattr(agent, "ainvoke"):
                    raise RuntimeError("Agent supports neither astream_events nor ainvoke — cannot run prompt")
                console.print(
                    "[yellow]Warning: Agent does not support streaming events. Using ainvoke instead.[/yellow]"
                )
                result = await agent.ainvoke(prompt_text, thread_id=invoke_tid)
                stream_text.append(result.output or "")
            else:
                with Live(
                    _live_agent_panel(thinking_lines, stream_text),
                    console=console,
                    refresh_per_second=_LIVE_REFRESH_HZ,
                    transient=True,
                    # "visible" stacks duplicate frames on some Windows terminals with Group+Panel.
                    vertical_overflow="crop",
                ) as live:
                    async for event in agent.astream_events(prompt_text, thread_id=invoke_tid):
                        event_type = event.type
                        data = event.data

                        if event_type in (
                            "thinking",
                            "llm_call",
                            "worker_start",
                            "worker_end",
                            "cache_hit",
                            "reflection",
                            "fallback",
                        ):
                            _append_trace_line(thinking_lines, event_type, data)
                            live.update(_live_agent_panel(thinking_lines, stream_text))

                        elif event_type == "token":
                            content = data.get("content", "")
                            if content:
                                stream_text.append(str(content))
                            live.update(_live_agent_panel(thinking_lines, stream_text))

                        elif event_type == "tool_call":
                            tool_name = data.get("name", "unknown")
                            tool_id = data.get("id", "")
                            tool_status[tool_id] = tool_name
                            tin = data.get("input", "")
                            tin_s = str(tin)[:120] + "…" if len(str(tin)) > 120 else str(tin)
                            thinking_lines.append(f"→ [yellow]{tool_name}[/yellow] {tin_s}")
                            live.update(_live_agent_panel(thinking_lines, stream_text))

                        elif event_type == "tool_result":
                            tool_id = data.get("id", "")
                            tool_name = tool_status.pop(tool_id, "unknown")
                            res = data.get("output", "")
                            preview = str(res)[:100] + "…" if len(str(res)) > 100 else str(res)
                            thinking_lines.append(f"  [green]✓[/green] {tool_name}: {preview}")
                            live.update(_live_agent_panel(thinking_lines, stream_text))

                        elif event_type == "error":
                            error_msg = data.get("error", "Unknown error")
                            thinking_lines.append(f"✗ {error_msg}")
                            live.update(_live_agent_panel(thinking_lines, stream_text))

                        elif event_type == "done":
                            # DIRECT short-circuit and other paths may never emit token chunks; use final output.
                            result = data.get("result") or {}
                            out = result.get("output", "")
                            if out and not stream_text.plain.strip():
                                stream_text.append(str(out))
                            live.update(_live_agent_panel(thinking_lines, stream_text))

            console.print()

            full_output = stream_text.plain
            _print_thinking_footer(thinking_lines, expanded=state.expand_thinking)
            if full_output.strip():
                console.print(
                    Panel(
                        full_output,
                        title="[bold green]Answer[/bold green]",
                        border_style="green",
                        padding=(0, 1),
                    )
                )
            state.add_turn(prompt_text, full_output)
            try:
                add_to_session_history(invoke_tid, "user", prompt_text)
                add_to_session_history(invoke_tid, "assistant", full_output)
            except Exception:
                pass

            console.print(
                Panel(
                    f"[green]✓[/green] [dim]Completed • {len(state.history)} turn(s)[/dim]",
                    border_style="green",
                    padding=(0, 1),
                )
            )
            console.print()

            console.print(
                _session_info_strip(
                    working_dir=working_dir,
                    status_model=status_model,
                    turns=len(state.history),
                    tokens_est=state.total_tokens_est,
                )
            )
            console.print()

        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted (Ctrl+C again to exit)[/dim]")
            try:
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                console.print("\n[dim]Goodbye! 👋[/dim]")
                break
        except Exception as e:
            if verbose:
                import traceback

                traceback.print_exc()
            console.print(f"\n[bold red]✗ Error:[/bold red] {e}")


def _show_help() -> None:
    """Show help with rich formatting."""
    console.print()
    console.print(
        Panel(
            """
[cyan]Available Commands:[/cyan]
  exit, quit, q    Exit the shell
  clear           Clear the screen
  history         View conversation history
  help            Show this help message
  thinking on|off | toggle   Compact vs full [dim]Reasoning[/dim] trace after each reply
                    (default: full; env [cyan]AGLOOM_EXPAND_THINKING=0[/cyan] for compact default)

  [dim]TTY shell uses Textual (scrollable chat + fixed session card); non-TTY runs auto-fallback to the line shell.[/dim]

[cyan]Built-in Tools:[/cyan]
  📁 Files:   read_file, write_file, edit_file, grep_files, list_directory, search_files
  📋 Edit:    copy_file, move_file, remove_file, create_directory
  🔧 Shell:   run_shell, run_shell_interactive, get_system_info
  📂 Paths:   get_working_directory, set_working_directory, path_*
  🌐 Env:     get_env_var, set_env_var, list_env_vars
        """.strip(),
            title="[cyan]Help[/cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()


if __name__ == "__main__":
    asyncio.run(run_shell(None))
