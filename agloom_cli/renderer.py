"""Terminal event rendering — pretty print agent events."""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

console = Console(
    theme=Theme(
        {
            "info": "cyan",
            "warning": "yellow",
            "error": "red bold",
            "success": "green",
            "path": "blue",
            "dim": "dim",
        }
    )
)


def render_event(event) -> None:
    """Render an AgentEvent to the terminal.

    Event types:
    - thinking: Classifier analysis
    - token: Streaming token
    - tool_call: Tool invocation
    - tool_result: Tool response
    - worker_start: Worker started
    - worker_end: Worker completed
    - error: Error occurred
    - done: Execution complete
    """
    event_type = event.type
    data = event.data

    if event_type == "thinking":
        output = data.get("output", "")
        if output:
            console.print(f"[dim]💭 {output}[/dim]")

    elif event_type == "token":
        content = data.get("content", "")
        console.print(content, end="")

    elif event_type == "tool_call":
        name = data.get("name", "unknown")
        tool_id = data.get("id", "")
        console.print(f"\n[yellow]🔧 {name}[/yellow]...", end=" ")
        return tool_id

    elif event_type == "tool_result":
        tool_id = data.get("id", "")
        result = data.get("output", "")
        preview = result[:120] + "..." if len(result) > 120 else result
        console.print(f"[success]✓[/success] [dim]{preview}[/dim]")

    elif event_type == "worker_start":
        name = data.get("name", "worker")
        console.print(f"[dim]⚡ Starting: {name}[/dim]")

    elif event_type == "worker_end":
        name = data.get("name", "worker")
        duration = data.get("duration_ms", 0)
        console.print(f"[dim]⚡ Done: {name} ({duration}ms)[/dim]")

    elif event_type == "llm_call":
        name = data.get("name", "llm")
        duration = data.get("duration_ms", 0)
        console.print(f"[dim]🔹 LLM call: {name} ({duration}ms)[/dim]")

    elif event_type == "reflection":
        output = data.get("output", "")
        if output:
            console.print(f"[dim]🔄 Reflection: {output[:100]}...[/dim]")

    elif event_type == "error":
        error = data.get("error", "Unknown error")
        console.print(f"\n[error]✗ Error: {error}[/error]")

    elif event_type == "done":
        pass

    return None


def render_result(result) -> None:
    """Render the final ExecutionResult."""
    console.print()
    if hasattr(result, "pattern_used") and result.pattern_used:
        console.print(f"[dim]Pattern: {result.pattern_used.value}[/dim]")
    if hasattr(result, "steps_taken"):
        console.print(f"[dim]Steps: {result.steps_taken}[/dim]")
    if hasattr(result, "token_usage") and result.token_usage:
        total = result.token_usage.get("total_tokens", 0)
        console.print(f"[dim]Tokens: {total}[/dim]")


def clear_line() -> None:
    """Clear the current line."""
    console.print("\r" + " " * 80 + "\r", end="")
