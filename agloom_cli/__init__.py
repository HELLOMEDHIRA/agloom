"""agloom CLI — Interactive agent shell."""

# Silence langgraph 1.1.x's *own* pending-deprecation warning (emitted at langchain_core's
# ``JsonPlusSerializer`` import — third-party, not agloom's deprecated usage). Keeps the CLI
# startup banner clean. Remove once langgraph drops the implicit ``allowed_objects`` default.
import warnings as _warnings

try:
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning as _LCWarn

    _warnings.filterwarnings("ignore", category=_LCWarn)
    del _LCWarn
except ImportError:
    pass

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("agloom")
except _PackageNotFoundError:
    __version__ = "0.0.0-dev"
del _PackageNotFoundError, _version, _warnings

# Note (E402 by design): warning suppression + version resolution must precede submodule imports
# that transitively load langgraph — moving them after these imports would surface the very
# deprecation warning we are trying to silence at CLI startup.
from .cli import app, console  # noqa: E402
from .tool_loader import discover_tools, tool  # noqa: E402
from .ui import RichUI, get_ui, reset_ui  # noqa: E402

__all__ = ["RichUI", "app", "console", "discover_tools", "get_ui", "reset_ui", "tool"]
