"""agloom CLI — Interactive agent shell."""

__version__ = "0.1.0"

from .cli import app, console
from .tool_loader import tool, discover_tools
from .ui import RichUI, get_ui, reset_ui

__all__ = ["app", "console", "tool", "discover_tools", "RichUI", "get_ui", "reset_ui"]
