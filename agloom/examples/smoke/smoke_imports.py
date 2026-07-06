"""Smoke test: import agloom and inspect version — no API key or network required."""

from __future__ import annotations

import agloom
from agloom import Signal, SignalType, create_agent


def main() -> None:
    print(f"agloom {agloom.__version__}")
    print(f"SignalType members: {[m.name for m in SignalType]}")
    assert callable(create_agent)
    assert Signal is not None
    print("smoke OK")


if __name__ == "__main__":
    main()
