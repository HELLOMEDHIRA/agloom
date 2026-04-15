"""agloom CLI — Interactive agent shell."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agloom")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

from .cli import app, console
from .tool_loader import discover_tools, tool
from .ui import RichUI, get_ui, reset_ui

__all__ = ["RichUI", "app", "console", "discover_tools", "get_ui", "reset_ui", "tool"]
