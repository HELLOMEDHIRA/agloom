"""
agloom.observability
─────────────────────
AI-native runtime observability platform for agloom.

AGP events are the source of truth.  Every Envelope is persisted to
SQLite and becomes queryable, replayable, and visualisable.

Public API::

    from agloom.observability import (
        ObservabilityStore,
        MetricsAggregator,
        ReplayEngine,
        make_obs_router,
        push_live_event,
    )

    # Open store
    store = await ObservabilityStore.open("agloom_obs.db")

    # Persist every envelope emitted by the runtime
    await store.ingest(envelope_dict)

    # Mount into FastAPI app
    app.include_router(make_obs_router(store), prefix="/observe")
"""

from .api import make_obs_router, push_live_event
from .metrics import MetricsAggregator, SessionMetrics
from .replay import ReplayEngine
from .store import EventRow, SessionSummary
from .store import SQLiteObservabilityStore as ObservabilityStore

__all__ = [
    # Store
    "ObservabilityStore",
    "SessionSummary",
    "EventRow",
    # Metrics
    "MetricsAggregator",
    "SessionMetrics",
    # Replay
    "ReplayEngine",
    # API
    "make_obs_router",
    "push_live_event",
]
