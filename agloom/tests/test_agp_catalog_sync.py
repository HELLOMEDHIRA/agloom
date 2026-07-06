"""AGP schema and cross-client catalogue sync checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agloom.protocol.schema import build_schema

_REPO = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO / "agloom" / "docs" / "protocol" / "agp-schema.json"
_CLI_EVENTS = _REPO / "agloom_cli" / "src" / "types" / "knownAgpEventTypes.ts"
_WEB_EVENTS = _REPO / "agloom_web" / "src" / "lib" / "agp" / "knownAgpEventTypes.ts"


def _extract_ts_event_set(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"'([a-z][a-z0-9_.]*)'", text))


def test_committed_agp_schema_includes_harness_synced() -> None:
    assert _SCHEMA_PATH.is_file(), "agp-schema.json missing — run: python -m agloom.protocol.schema --out agloom/docs/protocol/agp-schema.json"
    committed = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    built = build_schema()
    for key in ("harness.synced", "pattern.classified", "plan.preview", "runtime.ready"):
        assert key in json.dumps(committed), f"{key} missing from committed agp-schema.json"
        assert key in json.dumps(built), f"{key} missing from built schema"
def test_committed_agp_schema_matches_built_harness_defs() -> None:
    committed = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    built = build_schema()
    for def_name in ("HarnessSyncedData", "PatternClassifiedData", "RuntimeReadyData"):
        assert def_name in built.get("$defs", {}), f"built schema missing {def_name}"
        assert def_name in committed.get("$defs", {}), (
            f"{def_name} missing from committed agp-schema.json — "
            "run: python -m agloom.protocol.schema --out agloom/docs/protocol/agp-schema.json"
        )


def test_cli_and_web_known_agp_event_types_match() -> None:
    cli = _extract_ts_event_set(_CLI_EVENTS)
    web = _extract_ts_event_set(_WEB_EVENTS)
    assert cli == web, f"CLI/Web event catalogue drift: {sorted(cli ^ web)}"


def test_known_events_include_harness_synced() -> None:
    cli = _extract_ts_event_set(_CLI_EVENTS)
    assert "harness.synced" in cli
    assert "progress.step" in cli
