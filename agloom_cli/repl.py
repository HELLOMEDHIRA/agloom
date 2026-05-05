"""Interactive REPL shell — Deep Agents / Claude Code style rich UI.

**Thinking** in the UI is **not** Python logging. It is the live **AgentEvent** stream from
``astream_events`` (classify / pattern / tool_start / tool_end / tokens, etc.) — the same
class of signal a product shell would show as “reasoning” or tool activity.

**INFO logs** from frameworks and ``agloom.*`` (including during ``create_agent``) are **filtered
off the console** for the whole CLI run unless ``--verbose`` — see ``agloom_cli.quiet_logs``.
"""

from __future__ import annotations

import asyncio
import os

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from . import __version__
from .config import add_to_session_history, get_session_history
from .ui import RichUI, get_ui, reset_ui

console = Console()

_THINKING_SCROLL_LINES = 16


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


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


def _thinking_panel(thinking_lines: list[str]) -> Panel:
    chunk = thinking_lines[-_THINKING_SCROLL_LINES:] if thinking_lines else []
    body = "\n".join(chunk) if chunk else "[dim]…[/dim]"
    extra = len(thinking_lines) - len(chunk)
    sub = f"[dim]↑ {extra} earlier step(s)[/dim]" if extra > 0 else None
    return Panel(
        body,
        title="[bold cyan]Thinking[/bold cyan]",
        border_style="dim",
        subtitle=sub,
        subtitle_align="left",
        padding=(0, 1),
    )


def _live_layout(thinking_lines: list[str], stream: Text) -> Group:
    parts: list = [_thinking_panel(thinking_lines)]
    if stream.plain:
        parts.append(
            Panel(
                stream,
                title="[bold green]Assistant[/bold green]",
                border_style="green",
                padding=(0, 1),
            )
        )
    return Group(*parts)


def _print_thinking_footer(thinking_lines: list[str], *, expanded: bool) -> None:
    """After a turn, show a compact or full trace (collapsible-style default)."""
    if not thinking_lines:
        return
    if expanded:
        console.print(
            Panel(
                "\n".join(thinking_lines),
                title="[bold cyan]Thinking[/bold cyan] [dim](full)[/dim]",
                border_style="dim",
                padding=(0, 1),
            )
        )
    else:
        last = thinking_lines[-1]
        preview = last if len(last) <= 100 else last[:100] + "…"
        console.print(
            Panel(
                f"[dim]▶[/dim] [bold]Thinking[/bold] — {len(thinking_lines)} step(s)\n"
                f"[dim]{preview}[/dim]\n"
                f"[dim]Full trace:[/dim] [cyan]thinking on[/cyan] [dim]· env[/dim] "
                f"[cyan]AGLOOM_EXPAND_THINKING=1[/cyan]",
                border_style="dim",
                padding=(0, 1),
            )
        )


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
        self.ui: RichUI = get_ui(console)
        self.expand_thinking: bool = _env_truthy("AGLOOM_EXPAND_THINKING")

    def add_turn(self, query: str, output: str) -> None:
        self.history.append((query, output))
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
) -> None:
    """Run interactive shell - Deep Agents / Claude Code style UI.

    Features:
    - Status bar with LangSmith, thread ID, MCP tools (banner printed by CLI before ``run_shell``)
    - Chat-style message display
    - Blue bordered input with bottom status
    - Keyboard shortcut hints
    - Rich thinking indicator
    - Tool call visualization
    """
    reset_ui()
    state = ShellState()

    working_dir = os.getcwd()
    state.ui.working_dir = working_dir
    state.ui.langsmith_enabled = bool(os.environ.get("LANGCHAIN_TRACING_V2"))

    invoke_tid = thread_id or state.ui.thread_id
    state.ui.thread_id = invoke_tid[:8] if len(invoke_tid) > 8 else invoke_tid

    pending_u: str | None = None
    for m in get_session_history(invoke_tid):
        role = str(m.get("role") or "").lower()
        content = str(m.get("content") or "")
        if role == "user":
            pending_u = content
        elif role == "assistant" and pending_u is not None:
            state.add_turn(pending_u, content)
            pending_u = None

    langsmith_status = (
        "[bold green]✓[/bold green] [dim]LangSmith: enabled (agloom-cli)[/dim]"
        if state.ui.langsmith_enabled
        else "[dim]○ LangSmith: disabled[/dim]"
    )

    console.print(
        Panel(
            f"{langsmith_status}\n"
            f"[dim]Thread: [cyan]{state.ui.thread_id}[/cyan][/dim]\n"
            f"[bold green]✓[/bold green] [bold green]{welcome}[/bold green]",
            border_style="green",
            padding=(0, 2),
            title="[bold]STATUS[/bold]",
        )
    )
    console.print()

    status_model = llm_status or "auto:auto"
    console.print(
        Panel(
            f"[green]●[/green] [green]session[/green]  "
            f"[dim]shift+tab to cycle[/dim]  "
            f"[dim]{working_dir}[/dim]  "
            f"[dim]0 tokens[/dim]  "
            f"[cyan]{status_model}[/cyan]",
            border_style="dim",
            padding=(0, 1),
            title="[dim]INFO[/dim]",
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
                    _live_layout(thinking_lines, stream_text),
                    console=console,
                    refresh_per_second=12,
                    transient=True,
                    vertical_overflow="visible",
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
                            live.update(_live_layout(thinking_lines, stream_text))

                        elif event_type == "token":
                            content = data.get("content", "")
                            if content:
                                stream_text.append(str(content))
                                live.update(_live_layout(thinking_lines, stream_text))

                        elif event_type == "tool_call":
                            tool_name = data.get("name", "unknown")
                            tool_id = data.get("id", "")
                            tool_status[tool_id] = tool_name
                            tin = data.get("input", "")
                            tin_s = str(tin)[:120] + "…" if len(str(tin)) > 120 else str(tin)
                            thinking_lines.append(f"→ [yellow]{tool_name}[/yellow] {tin_s}")
                            live.update(_live_layout(thinking_lines, stream_text))

                        elif event_type == "tool_result":
                            tool_id = data.get("id", "")
                            tool_name = tool_status.pop(tool_id, "unknown")
                            res = data.get("output", "")
                            preview = str(res)[:100] + "…" if len(str(res)) > 100 else str(res)
                            thinking_lines.append(f"  [green]✓[/green] {tool_name}: {preview}")
                            live.update(_live_layout(thinking_lines, stream_text))

                        elif event_type == "error":
                            error_msg = data.get("error", "Unknown error")
                            thinking_lines.append(f"✗ {error_msg}")
                            live.update(_live_layout(thinking_lines, stream_text))

            console.print()

            full_output = stream_text.plain
            _print_thinking_footer(thinking_lines, expanded=state.expand_thinking)
            if full_output.strip():
                console.print(
                    Panel(
                        full_output,
                        title="[bold green]Assistant[/bold green]",
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

            token_count = len(prompt_text + full_output) // 4

            console.print(
                Panel(
                    f"[green]✓[/green] [dim]Completed • {len(state.history)} turn(s)[/dim]",
                    border_style="green",
                    padding=(0, 1),
                )
            )
            console.print()

            console.print(
                Panel(
                    f"[green]●[/green] [green]session[/green]  "
                    f"[dim]shift+tab to cycle[/dim]  "
                    f"[dim]{working_dir}[/dim]  "
                    f"[dim]{token_count:,} tokens[/dim]  "
                    f"[cyan]{status_model}[/cyan]",
                    border_style="dim",
                    padding=(0, 1),
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
  thinking on|off | toggle   Show full vs compact [dim]Thinking[/dim] trace after each reply
                    (or env [cyan]AGLOOM_EXPAND_THINKING=1[/cyan])

[cyan]Built-in Tools:[/cyan]
  📁 Files:   read_file, write_file, list_directory, search_files
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
