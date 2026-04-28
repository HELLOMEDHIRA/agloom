"""Run ``agsuperbrain init`` in the project so the Super-Brain MCP index is ready for CLI agent runs."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

console = Console()


def agsuperbrain_installed() -> bool:
    return importlib.util.find_spec("agsuperbrain") is not None


def _superbrain_init_argv() -> list[str]:
    exe = shutil.which("agsuperbrain")
    if exe:
        return [exe, "init"]
    return [sys.executable, "-m", "agsuperbrain", "init"]


def run_agsuperbrain_init(project: Path, *, env: dict[str, str] | None = None, quiet: bool = False) -> int:
    """Run ``agsuperbrain init`` in ``project`` (ingest / index). Required before each CLI agent run."""
    argv = _superbrain_init_argv()
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    if not quiet:
        console.print(f"[dim]Super-Brain:[/dim] {' '.join(argv)} [dim]in {project}[/dim]")
    # argv is fully constant (sys.executable + literals) — no untrusted input
    proc = subprocess.run(argv, cwd=project, env=merged_env, shell=False)  # noqa: S603
    return int(proc.returncode)
