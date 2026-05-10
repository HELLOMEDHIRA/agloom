"""Legacy ``agloom`` console script — compatibility shim after the CLI moved to Node.js."""

from __future__ import annotations

import sys

_NOTICE = """\
The interactive terminal CLI is not installed by the Python package anymore.

Install and run the agloom CLI from ``agloom_cli/`` (Node.js ≥24.15 per ``package.json``; terminal UI uses Ink + React)::

    cd agloom_cli && npm install && npm run build && npm start

Run the AGP runtime that powers every frontend::

    agloom-runtime serve --transport=stdio

Library usage is unchanged::

    from agloom import create_agent

Documentation: https://agloom.readthedocs.io
"""


def main() -> None:
    """Print migration notice and exit with code 2."""
    sys.stderr.write(_NOTICE)
    sys.stderr.flush()
    raise SystemExit(2)
