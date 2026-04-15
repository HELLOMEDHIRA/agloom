"""Interactive REPL shell — Deep Agents / Claude Code style rich UI."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import pyfiglet
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from .ui import RichUI, get_ui, reset_ui


console = Console()


def render_banner(text: str = "AGLOOM") -> Panel:
    """Render text as ASCII art using pyfiglet with rich styling."""
    font = "small"
    fig = pyfiglet.Figlet(font=font, width=120)
    ascii_art = fig.renderText(text)

    t = Text(ascii_art, style="bold cyan")

    return Panel.fit(
        t,
        border_style="cyan",
        padding=(0, 1),
        subtitle=f"[cyan]v0.1.0[/cyan]",
        subtitle_align="right",
    )


class ShellState:
    """Manages shell state across sessions."""

    def __init__(self):
        self.history: list[tuple[str, str]] = []
        self.session_id: str | None = None
        self.ui: RichUI = get_ui(console)

    def add_turn(self, query: str, output: str) -> None:
        self.history.append((query, output))
        self.ui.add_to_history(query, output)

    def get_history(self) -> list[tuple[str, str]]:
        return self.history


async def run_shell(
    agent,
    *,
    welcome: str = "Ready to code!",
) -> None:
    """Run interactive shell - Deep Agents / Claude Code style UI.

    Features:
    - ASCII art header with logo
    - Status bar with LangSmith, thread ID, MCP tools
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

    ascii_banner = render_banner("AGLOOM")
    console.print(ascii_banner)
    console.print()

    thread_id = state.ui.thread_id
    tools_count = len(agent.config.get("tools", []))

    console.print(
        Panel(
            f"[bold green]✓[/bold green] [dim]LangSmith: enabled (agloom-cli)[/dim]\n"
            f"[dim]Thread: [cyan]{thread_id}[/cyan][/dim]\n"
            f"[bold green]✓[/bold green] [dim]Loaded [cyan]{tools_count}[/cyan] tool(s)[/dim]\n"
            f"[bold green]✓[/bold green] [bold green]{welcome}[/bold green]",
            border_style="green",
            padding=(0, 2),
            title="[bold]STATUS[/bold]",
        )
    )
    console.print()

    console.print(
        Panel(
            f"[bold blue]❯[/bold blue] [dim]Type your message...[/dim]\n\n"
            f"[dim]Enter send • Ctrl+J newline • @ files • / commands[/dim]",
            border_style="blue",
            padding=(1, 2),
            title="[bold]INPUT[/bold]",
        )
    )
    console.print()

    model_name = "auto"
    console.print(
        Panel(
            f"[bold green]●[/bold green] [bold green]auto[/bold green]  "
            f"[dim]shift+tab to cycle[/dim]  "
            f"[cyan]{working_dir}[/cyan]  "
            f"[yellow]0 tokens[/yellow]  "
            f"[blue]openai:{model_name}[/blue]",
            border_style="dim",
            padding=(0, 1),
            title="[dim]INFO[/dim]",
        )
    )
    console.print()

    console.print(
        Panel(
            f"[bold blue]❯[/bold blue] [dim]Type your message...[/dim]\n\n"
            f"[dim]Enter send • Ctrl+J newline • @ files • / commands[/dim]",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()

    model_name = "auto"
    console.print(
        Panel(
            f"[green]●[/green] [green]auto[/green]  "
            f"[dim]shift+tab to cycle[/dim]  "
            f"[dim]{working_dir}[/dim]  "
            f"[dim]0 tokens[/dim]  "
            f"[dim]openai:{model_name}[/dim]",
            border_style="dim",
            padding=(0, 1),
        )
    )
    console.print()

    while True:
        try:
            prompt_text = Prompt.get(
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
                await run_shell(agent, welcome="Shell cleared")
                return

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

            console.print()
            console.print(
                Panel(
                    f"[bold magenta]>[bold magenta] {prompt_text}",
                    border_style="magenta",
                    padding=(0, 1),
                )
            )
            console.print()

            output_parts: list[str] = []
            tool_status: dict = {}

            with console.status("[bold cyan]🤔 Thinking...", spinner="dots") as status:
                async for event in agent.astream_events(prompt_text):
                    event_type = event.type
                    data = event.data

                    if event_type == "thinking":
                        output_preview = data.get("output", "")
                        if output_preview:
                            status.update(f"[cyan]🤔 {output_preview[:40]}...")

                    elif event_type == "token":
                        content = data.get("content", "")
                        output_parts.append(content)
                        console.print(content, end="")

                    elif event_type == "tool_call":
                        tool_name = data.get("name", "unknown")
                        tool_id = data.get("id", "")
                        tool_status[tool_id] = tool_name
                        console.print(f"\n[yellow]🔧[/yellow] [bold]{tool_name}[/bold]...", end=" ", flush=True)

                    elif event_type == "tool_result":
                        tool_id = data.get("id", "")
                        tool_name = tool_status.pop(tool_id, "unknown")
                        result = data.get("output", "")
                        preview = result[:80] + "..." if len(result) > 80 else result
                        console.print(f"[green]✓[/green] [dim]{preview}[/dim]")

                    elif event_type == "error":
                        error_msg = data.get("error", "Unknown error")
                        console.print(f"\n[bold red]✗ Error:[/bold red] {error_msg}")

            console.print()

            full_output = "".join(output_parts)
            state.add_turn(prompt_text, full_output)

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
                    f"[green]●[/green] [green]auto[/green]  "
                    f"[dim]shift+tab to cycle[/dim]  "
                    f"[dim]{working_dir}[/dim]  "
                    f"[dim]{token_count:,} tokens[/dim]  "
                    f"[dim]openai:{model_name}[/dim]",
                    border_style="dim",
                    padding=(0, 1),
                )
            )
            console.print()

        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted (Ctrl+C again to exit)[/dim]")
            try:
                await asyncio.sleep(0.5)
            except KeyboardInterrupt:
                console.print("\n[dim]Goodbye! 👋[/dim]")
                break
        except Exception as e:
            console.print(f"\n[bold red]✗ Error:[/bold red] {e}")
            if "-v" in sys.argv or "--verbose" in sys.argv:
                import traceback

                traceback.print_exc()


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
