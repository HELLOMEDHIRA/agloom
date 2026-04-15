"""Human-in-the-loop approval handler for CLI."""

from __future__ import annotations

import re

from rich.console import Console
from rich.prompt import Prompt

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


def create_user_callback(
    auto_approve_tools: list[str] | None = None,
    require_all: bool = False,
):
    """Create a user_callback for agloom that prompts for human approval.

    When --require-approval is used, this callback will be triggered
    when interrupt_before_tools is hit. The message will contain
    info about which tool is being called.

    Args:
        auto_approve_tools: Tools to auto-approve without prompting
        require_all: Require approval for all tools, not just sensitive ones

    Returns:
        Async callback function for agloom
    """
    auto_list = auto_approve_tools or []

    async def callback(event_type: str, message: str) -> bool:
        if event_type == "pattern_interrupt":
            # Extract tool name from the interrupt message
            # Message format: "interrupt_before_tools: run_shell"

            tool_name = None

            # Try to extract tool name from message
            if "interrupt_before_tools" in message.lower():
                # Parse tool name from message like "interrupt_before_tools: run_shell"
                match = re.search(
                    r"(run_shell|write_file|remove_file|copy_file|move_file|set_working_directory|http_request|http_post|http_put|http_delete)",
                    message,
                    re.IGNORECASE,
                )
                if match:
                    tool_name = match.group(1).lower()

            # If no tool name found, try to detect from message
            if not tool_name:
                for sensitive in SENSITIVE_TOOLS:
                    if sensitive.lower() in message.lower():
                        tool_name = sensitive
                        break

            if not tool_name:
                # Not a tool interrupt, just show message
                console.print(f"[dim]{message}[/dim]")
                return True

            # Check if this tool should be auto-approved
            if tool_name in auto_list:
                console.print(f"[green]✓ Auto-approved: {tool_name}[/green]")
                return True

            # Show approval prompt
            description = SENSITIVE_TOOLS.get(tool_name, f"execute {tool_name}")

            console.print()
            console.print("[bold yellow]⚠️  Human Approval Required[/bold yellow]")
            console.print(f"[yellow]Tool:[/yellow] {tool_name}")
            console.print(f"[yellow]Action:[/yellow] {description}")
            console.print()

            response = Prompt.ask(
                "[bold red]Do you want to proceed?[/bold red] [dim](y/n)[/dim]",
                choices=["y", "n", "yes", "no"],
                default="n",
            )

            return response.lower() in ["y", "yes"]

        return True

    return callback
