"""JSON Schema export for the Agloom Protocol (AGP).

Generates a single ``agp-schema.json`` that TypeScript, Rust, and other typed
consumers can validate against.  The schema is derived directly from the Pydantic
models in :mod:`agloom.protocol.events` — it is always in sync with the Python
implementation.

CLI usage::

    python -m agloom.protocol.schema          # prints to stdout
    python -m agloom.protocol.schema --out agp-schema.json

Programmatic usage::

    from agloom.protocol.schema import build_schema, write_schema
    schema = build_schema()                   # -> dict
    write_schema(Path("agp-schema.json"))     # writes the file
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from .commands import Command
from .events import Event


def build_schema() -> dict[str, Any]:
    """Return the full AGP JSON Schema as a Python dict.

    The top-level schema is a ``oneOf`` over all concrete event types, keyed by the
    ``type`` discriminator so validators can cheaply dispatch to the right sub-schema.
    The ``$defs`` section contains all shared models (envelope fields, data models).

    Inbound **commands** (client → runtime) share ``$defs`` and are exposed under the
    auxiliary key ``agp_commands`` — same JSON object shape as on the wire
    (``type`` + ``data``, no session envelope).
    """
    adapter: TypeAdapter[Event] = TypeAdapter(Event)
    raw: dict[str, Any] = adapter.json_schema(mode="serialization")

    cmd_adapter: TypeAdapter[Command] = TypeAdapter(Command)
    cmd_raw: dict[str, Any] = cmd_adapter.json_schema(mode="serialization")

    defs = raw.setdefault("$defs", {})
    for key, val in cmd_raw.get("$defs", {}).items():
        if key in defs and defs[key] != val:
            raise ValueError(f"AGP schema merge collision in $defs[{key!r}]")
        defs[key] = val

    raw["agp_commands"] = {
        "title": "AGP inbound commands",
        "description": (
            "Typed JSON objects sent on the NDJSON stream from client to runtime — "
            "discriminated by top-level ``type`` (``command.*``). No AGP envelope fields."
        ),
        **{k: v for k, v in cmd_raw.items() if k != "$defs"},
    }

    # Inject top-level metadata consumers expect.
    raw.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    raw.setdefault("title", "AGP Event")
    raw.setdefault(
        "description",
        (
            "Agloom Protocol (AGP) v1 — discriminated union over all known event types. "
            "Parse with the 'type' field as the discriminator. "
            "Unknown 'type' values MUST be forwarded rather than rejected (forward-compat rule)."
        ),
    )
    return raw


def write_schema(path: Path) -> None:
    """Write the AGP JSON Schema to *path* (creates parent dirs as needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = build_schema()
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


def _main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m agloom.protocol.schema",
        description="Export the AGP JSON Schema derived from Pydantic models.",
    )
    parser.add_argument(
        "--out",
        metavar="FILE",
        default=None,
        help="Write schema to FILE (default: print to stdout).",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent width (default: 2).",
    )
    args = parser.parse_args()

    schema = build_schema()
    serialised = json.dumps(schema, indent=args.indent) + "\n"

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(serialised, encoding="utf-8")
        sys.stderr.write(f"[agp-schema] wrote {out_path} ({len(serialised)} bytes)\n")
    else:
        sys.stdout.write(serialised)


if __name__ == "__main__":
    _main()


__all__ = ["build_schema", "write_schema"]
