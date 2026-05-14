"""AGP envelope — fields every event carries on the wire.

Concrete event classes (in :mod:`agloom.protocol.events`) extend :class:`Envelope` and add a
``type`` literal + a typed ``data`` payload. The discriminated union over ``type`` lives in
:mod:`agloom.protocol.events` for parsers.

Compatibility rules (must hold across the lifetime of ``v=1``):

- New event types are **additive**. Consumers MUST forward unknown ``type`` values rather than
  raising. New optional fields on existing events are likewise additive.
- ``v`` is bumped only on a breaking change; that change ships its own envelope class.
- ``id`` / ``ts`` / ``seq`` formats are opaque strings/ints — do not parse meaning out of them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION: Literal["1"] = "1"
"""Major version of the Agloom Protocol. Bumped only on breaking schema changes."""


def _protocol_module_version() -> str:
    """Same version as the ``agloom`` distribution (:file:`pyproject.toml` ``project.version``).

    Uses installed package metadata when available; otherwise walks upward from this file to find
    ``pyproject.toml`` (e.g. bare ``PYTHONPATH`` runs without an install).
    """
    try:
        return _distribution_version("agloom")
    except PackageNotFoundError:
        pass
    import tomllib

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "pyproject.toml"
        if not candidate.is_file():
            continue
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except OSError:
            break
        ver = data.get("project", {}).get("version")
        if isinstance(ver, str) and ver.strip():
            return ver.strip()
        break
    return "0.0.0+unknown"


_protocol_module_version_cache: str | None = None


def __getattr__(name: str) -> Any:
    """Lazy :data:`PROTOCOL_MODULE_VERSION` — avoids ``pyproject`` walk when only ``Envelope`` is imported."""
    if name == "PROTOCOL_MODULE_VERSION":
        global _protocol_module_version_cache
        if _protocol_module_version_cache is None:
            _protocol_module_version_cache = _protocol_module_version()
        return _protocol_module_version_cache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def new_event_id() -> str:
    """Mint a unique, time-ordered-ish event id.

    Currently a uuid4 hex prefix; may upgrade to ULID without changing the wire format
    (consumers must treat the value as opaque).
    """
    return f"evt_{uuid4().hex[:24]}"


def now_utc() -> datetime:
    """Aware UTC ``datetime`` used as the default for ``Envelope.ts``."""
    return datetime.now(UTC)


class Envelope(BaseModel):
    """Common AGP envelope fields. Extended by every concrete event type.

    Fields are documented in ``agloom/docs/protocol/agp.md``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    v: Literal["1"] = PROTOCOL_VERSION
    id: str = Field(default_factory=new_event_id)
    ts: datetime = Field(default_factory=now_utc)
    session: str
    thread: str
    seq: int = Field(ge=0)
    parent: str | None = None
    trace: str | None = None


__all__ = ["PROTOCOL_MODULE_VERSION", "PROTOCOL_VERSION", "Envelope", "new_event_id", "now_utc"]
