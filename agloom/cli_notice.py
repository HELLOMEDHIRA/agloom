"""Legacy ``agloom`` console script — compatibility shim after the terminal client moved to npm."""

from __future__ import annotations

import sys

_NOTICE = """\
The ``agloom`` terminal program is not part of the PyPI ``agloom`` package.
It is published separately as the **agloom-cli** npm package.

Install the CLI (requires a current Node.js LTS from https://nodejs.org)::

    npm install -g agloom-cli

Then run ``agloom`` from your terminal. Docs: https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/

To run only the Python AGP runtime (what the CLI and other frontends attach to)::

    agloom-runtime serve --transport=stdio

Python library usage is unchanged::

    from agloom import create_agent

Project home and full documentation: https://agloom.readthedocs.io
"""


def main() -> None:
    """Print migration notice and exit with code 2."""
    sys.stderr.write(_NOTICE)
    sys.stderr.flush()
    raise SystemExit(2)
