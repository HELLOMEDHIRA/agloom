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
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION: Literal["1"] = "1"
"""Major version of the Agloom Protocol. Bumped only on breaking schema changes."""

PROTOCOL_MODULE_VERSION = "0.1.54"
"""Version of this *implementation* of AGP — distinct from :data:`PROTOCOL_VERSION`.

Bumped whenever this Python package's behaviour changes (additive event types, perf, bug fixes).
The on-the-wire ``v`` field is :data:`PROTOCOL_VERSION` and changes only on breaking schema bumps.
"""


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


__all__ = ["PROTOCOL_VERSION", "Envelope", "new_event_id", "now_utc"]
