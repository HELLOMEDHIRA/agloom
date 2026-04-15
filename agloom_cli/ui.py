"""Rich UI components — Deep Agents style."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text


class RichUI:
    """Rich UI like Deep Agents / Claude Code CLI."""

    VERSION = "0.1.0"
    THEME = {
        "primary": "cyan",
        "secondary": "green",
        "accent": "blue",
        "warning": "yellow",
        "error": "red",
        "dim": "dim",
        "user": "cyan",
        "assistant": "green",
    }

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self.thread_id = self._generate_thread_id()
        self.token_count = 0
        self.working_dir = ""
        self.model_name = "auto"
        self.langsmith_enabled = False
        self.mcp_tools_loaded = 0
        self._history: list[dict] = []

    def _generate_thread_id(self) -> str:
        return uuid.uuid4().hex[:8]

    # ═══════════════════════════════════════════════════════════════════════════
    # HEADER - ASCII Art Logo
    # ═══════════════════════════════════════════════════════════════════════════

    def render_header(self) -> Panel:
        """Render ASCII art header like Deep Agents."""
        logo = """
[bold cyan]╔════════════════════════════════════════════════════════════╗
║  ██████╗  ██████╗  ██████╗ ████████╗    ██████╗  █████╗  ██████╗██╗  ██╗
║  ██╔══██╗ ██╔═══██╗ ██╔══██╗╚══██╔══╝   ██╔═══██╗██╔══██╗██╔════╝██║ ██╔╝
║  ██████╔╝ ██║   ██║ ██║  ██║   ██║      ██║   ██║███████║██║     █████╔╝ 
║  ██╔══██╗ ██║   ██║ ██║  ██║   ██║      ██║   ██║██╔══██║██║     ██╔═██╗ 
║  ██████╔╝ ╚██████╔╝ ██████╔╝   ██║      ╚██████╔╝██║  ██║╚██████╗██║  ██╗
║  ╚═════╝   ╚═════╝  ╚═════╝    ╚═╝       ╚═════╝ ╚═╝  ╚═╝ ╚══════╝╚═╝  ╚═╝
╚════════════════════════════════════════════════════════════╝[/bold cyan]
        """
        version_text = f"[dim]v{self.VERSION}[/dim]"

        header = Text()
        header.append(logo.rstrip(), style="cyan")
        header.append("  ", style="dim")
        header.append(version_text, style="dim")

        return Panel(
            header,
            border_style="cyan",
            padding=(0, 1),
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # STATUS BAR
    # ═══════════════════════════════════════════════════════════════════════════

    def render_status_bar(self, ready_message: str = "Ready to code!") -> Panel:
        """Render status bar with LangSmith, thread ID, MCP tools."""
        lines = []

        if self.langsmith_enabled:
            lines.append(f"[green]✓[/green] [dim]LangSmith tracing: 'agloom-cli'[/dim]")
        else:
            lines.append(f"[dim]○ LangSmith: disabled[/dim]")

        lines.append(f"[dim]Thread: {self.thread_id}[/dim]")

        if self.mcp_tools_loaded > 0:
            lines.append(f"[green]✓[/green] [dim]Loaded {self.mcp_tools_loaded} MCP tool(s)[/dim]")
        else:
            lines.append(f"[dim]MCP: none loaded[/dim]")

        lines.append(f"[green]✓[/green] [green]{ready_message}[/green]")

        content = "\n".join(lines)

        return Panel(
            content,
            border_style="green",
            padding=(0, 1),
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # CHAT AREA
    # ═══════════════════════════════════════════════════════════════════════════

    def render_user_message(self, message: str) -> Panel:
        """Render user message in chat area."""
        return Panel(
            f"[bold magenta]>[/bold magenta] {message}",
            border_style="magenta",
            padding=(0, 1),
        )

    def render_assistant_message(self, message: str) -> Panel:
        """Render assistant message in chat area."""
        return Panel(
            message,
            border_style="green",
            padding=(0, 1),
        )

    def render_message_pair(self, user_msg: str, assistant_msg: str) -> None:
        """Render a user + assistant message pair."""
        self.console.print(self.render_user_message(user_msg))
        self.console.print()
        self.console.print(self.render_assistant_message(assistant_msg))
        self.console.print()

    def add_to_history(self, user_msg: str, assistant_msg: str) -> None:
        """Add message pair to history."""
        self._history.append(
            {
                "user": user_msg,
                "assistant": assistant_msg,
                "timestamp": datetime.now(),
            }
        )
        self._update_token_count(user_msg + assistant_msg)

    def _update_token_count(self, text: str) -> None:
        """Estimate token count (rough ~4 chars per token)."""
        self.token_count = len(text) // 4

    # ═══════════════════════════════════════════════════════════════════════════
    # INPUT SECTION
    # ═══════════════════════════════════════════════════════════════════════════

    def render_input_prompt(self) -> str:
        """Render input prompt (to use with input())."""
        return "[bold cyan]❯[/bold cyan] "

    def render_input_box(self) -> Panel:
        """Render input box with blue border."""
        content = f"""
[bold blue]❯[/bold blue] [dim]Type your message...[/dim]
        
[dim]Enter send • Ctrl+J newline • @ files • / commands[/dim]"""

        return Panel(
            content,
            border_style="blue",
            padding=(1, 2),
        )

    def render_bottom_status(self) -> Panel:
        """Render bottom status bar with model, tokens, working dir."""
        status_parts = [
            f"[green]●[/green] [green]auto[/green]",
            f"[dim]shift+tab to cycle[/dim]",
            f"[dim]{self.working_dir or '~'}[/dim]",
            f"[dim]{self.token_count:,} tokens[/dim]",
            f"[dim]openai:{self.model_name}[/dim]",
        ]

        content = "  ".join(status_parts)

        return Panel(
            content,
            border_style="dim",
            padding=(0, 1),
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # THINKING / LOADING
    # ═══════════════════════════════════════════════════════════════════════════

    def render_thinking(self, message: str = "Thinking...") -> Progress:
        """Create a thinking progress indicator."""
        return Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        )

    def render_tool_call(self, tool_name: str) -> None:
        """Render tool call with styling."""
        self.console.print(f"[yellow]🔧[/yellow] [bold]{tool_name}[/bold]...", end=" ", flush=True)

    def render_tool_result(self, result: str, success: bool = True) -> None:
        """Render tool result."""
        preview = result[:80] + "..." if len(result) > 80 else result
        color = "green" if success else "red"
        self.console.print(f"[{color}]✓[/{color}] [dim]{preview}[/dim]")

    # ═══════════════════════════════════════════════════════════════════════════
    # FULL RENDER
    # ═══════════════════════════════════════════════════════════════════════════

    def render_welcome(self, tools_count: int = 0) -> None:
        """Render complete welcome screen."""
        self.console.print(self.render_header())
        self.console.print()

        self.mcp_tools_loaded = tools_count
        self.console.print(self.render_status_bar("Ready to code!"))
        self.console.print()

        self.console.print(self.render_input_box())
        self.console.print()

        self.console.print(self.render_bottom_status())

    def render_chat_complete(self, user_msg: str, assistant_msg: str) -> None:
        """Render chat after completion."""
        self.console.print()
        self.console.print(self.render_user_message(user_msg))
        self.console.print()

        if assistant_msg:
            self.console.print(
                self.render_assistant_message(
                    assistant_msg[:500] + "..." if len(assistant_msg) > 500 else assistant_msg
                )
            )

        self.console.print()
        self.console.print(self.render_bottom_status())


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════

_ui_instance: RichUI | None = None


def get_ui(console: Console | None = None) -> RichUI:
    """Get or create UI singleton."""
    global _ui_instance
    if _ui_instance is None:
        _ui_instance = RichUI(console)
    return _ui_instance


def reset_ui() -> None:
    """Reset UI instance for new session."""
    global _ui_instance
    _ui_instance = None
