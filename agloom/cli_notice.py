"""Legacy ``agloom`` console script — forwards to ``agloom-cli`` (npm) when available."""

from __future__ import annotations

import os
import subprocess
import sys

_VERSION: str | None = None


def _get_version() -> str:
    global _VERSION
    if _VERSION is not None:
        return _VERSION
    try:
        from importlib.metadata import version
        _VERSION = version("agloom")
    except Exception:
        _VERSION = "unknown"
    return _VERSION


def _find_cli() -> str | None:
    """Look for the Node ``agloom`` (``agloom-cli``) on PATH, excluding the Python shim.
    
    Detection logic:
    - Windows: npm creates ``agloom.cmd``; pip creates ``agloom.exe`` (skipped).
    - Unix: both pip and npm create a script named ``agloom``.
      The pip version has a ``python`` shebang; the npm version has a ``node`` shebang.
    """
    this_file = os.path.abspath(__file__) if __file__ else None
    candidates: list[str] = ["agloom.cmd"] if sys.platform == "win32" else ["agloom"]
    for name in candidates:
        for p in os.environ.get("PATH", "").split(os.pathsep):
            full = os.path.join(p, name)
            if not os.path.isfile(full) or not os.access(full, os.X_OK):
                continue
            # Windows: .exe = pip-installed, .cmd = npm-installed
            if full.lower().endswith(".exe"):
                continue
            # Skip if it resolves to this same module (alias/symlink edge case)
            if this_file and os.path.abspath(full) == this_file:
                continue
            # Read shebang: npm installs a node script; pip installs a python script
            try:
                with open(full, "rb") as fh:
                    shebang = fh.read(80).decode("utf-8", errors="replace")
                if shebang.startswith("#!") and "node" in shebang.lower():
                    return full
                # If it's a .cmd or a script without shebang, still accept it
                if full.lower().endswith(".cmd"):
                    return full
            except Exception:
                pass
    return None


def main() -> None:
    """Forward to ``agloom-cli`` (npm) if installed; otherwise print notice."""
    args = sys.argv[1:]

    # --version: always show Python lib version + hint
    if args and args[0] in ("--version", "-V"):
        py_ver = _get_version()
        cli = _find_cli()
        if cli:
            try:
                r = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=15)
                cli_ver = r.stdout.strip() or r.stderr.strip() or "(unknown)"
            except Exception:
                cli_ver = "(could not check)"
            sys.stderr.write(f"agloom Python library {py_ver}\nagloom CLI {cli_ver}\n")
        else:
            sys.stderr.write(f"agloom Python library {py_ver}\n")
            sys.stderr.write("agloom CLI: npm install -g agloom-cli\n")
        sys.stderr.flush()
        raise SystemExit(0)

    # Try forwarding to Node CLI
    cli = _find_cli()
    if cli is not None:
        try:
            r = subprocess.run([cli] + args, shell=False)
        except FileNotFoundError:
            pass
        else:
            raise SystemExit(r.returncode)

    # No Node CLI found — show migration notice
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
    sys.stderr.write(_NOTICE)
    sys.stderr.flush()
    raise SystemExit(2)
