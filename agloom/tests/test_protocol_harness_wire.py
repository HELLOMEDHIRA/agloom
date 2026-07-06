"""AGP harness wire: structured harness_plan on pattern/plan events + harness.synced."""

from __future__ import annotations

import io

from agloom.protocol import SessionEmitter
from agloom.protocol.events import HarnessSynced, PatternClassified, PlanPreview, event_adapter
from agloom.protocol.harness_wire import harness_plan_tasks_wire
from agloom.src.models import HarnessPlanTask, PatternType, QueryAnalysis
from agloom.runtime.translator import translate
from agloom.src.models import AgentEvent


class _RecordingEmitter(SessionEmitter):
    def __init__(self) -> None:
        super().__init__(session="s", thread="t", writer=io.StringIO())
        self.calls: list[tuple[str, dict]] = []

    def emit_pattern_classified(self, **kw):  # type: ignore[no-untyped-def]
        self.calls.append(("emit_pattern_classified", kw))
        return super().emit_pattern_classified(**kw)

    def emit_harness_synced(self, **kw):  # type: ignore[no-untyped-def]
        self.calls.append(("emit_harness_synced", kw))
        return super().emit_harness_synced(**kw)


def test_harness_plan_tasks_wire_from_analysis() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=6,
        reasoning="investigate",
        harness_work_kind="investigation",
        harness_plan=[
            HarnessPlanTask(
                task_id="ctx-1",
                description="Collect timeline",
                verification_steps=["Timeline documented"],
            )
        ],
    )
    wire = harness_plan_tasks_wire(analysis)
    assert len(wire) == 1
    assert wire[0].task_id == "ctx-1"


def test_translate_classify_includes_harness_plan() -> None:
    em = _RecordingEmitter()
    translate(
        AgentEvent(
            type="classify",
            data={
                "pattern": "REACT",
                "complexity": 5,
                "reason": "needs tools",
                "harness_work_kind": "investigation",
                "harness_plan": [
                    {
                        "task_id": "ctx-1",
                        "description": "Collect timeline",
                        "category": "planned",
                        "priority": "high",
                        "verification_steps": ["ok"],
                    }
                ],
            },
        ),
        em,
    )
    assert em.calls[0][0] == "emit_pattern_classified"
    kw = em.calls[0][1]
    assert kw["harness_work_kind"] == "investigation"
    assert len(kw["harness_plan"]) == 1
    assert kw["harness_plan"][0].task_id == "ctx-1"


def test_pattern_classified_round_trip_json() -> None:
    from agloom.protocol.events import HarnessPlanTaskWire, PatternClassifiedData

    payload = PatternClassifiedData(
        pattern="REACT",
        complexity=5,
        harness_work_kind="investigation",
        harness_plan=[
            HarnessPlanTaskWire(task_id="a", description="do work", verification_steps=["verify"]),
        ],
    )
    evt = PatternClassified(session="s", thread="t", seq=1, data=payload)
    parsed = event_adapter.validate_python(evt.model_dump())
    assert isinstance(parsed, PatternClassified)
    assert parsed.data.harness_plan[0].task_id == "a"


def test_emit_plan_preview_harness_fields() -> None:
    em = SessionEmitter(session="s", thread="t", writer=io.StringIO())
    from agloom.protocol.events import HarnessPlanTaskWire

    evt = em.emit_plan_preview(
        pattern="REACT",
        complexity=4,
        reasoning="rca",
        steps=["1. investigate"],
        harness_work_kind="investigation",
        harness_plan=[HarnessPlanTaskWire(task_id="t1", description="step")],
    )
    assert isinstance(evt, PlanPreview)
    assert evt.data.harness_plan[0].task_id == "t1"


def test_translate_harness_synced() -> None:
    em = _RecordingEmitter()
    translate(
        AgentEvent(
            type="harness.synced",
            data={
                "action": "seed",
                "tasks_synced": 1,
                "work_kind": "investigation",
                "completion_ratio": 0.0,
                "task_count": 1,
                "harness_plan": [{"task_id": "a", "description": "d"}],
                "tasks": [{"task_id": "a", "description": "d", "status": "pending"}],
            },
        ),
        em,
    )
    assert em.calls[0][0] == "emit_harness_synced"
    assert em.calls[0][1]["action"] == "seed"
    assert em.calls[0][1]["task_count"] == 1


def test_harness_synced_event_adapter() -> None:
    from agloom.protocol.events import HarnessLedgerTaskWire, HarnessSyncedData

    evt = HarnessSynced(
        session="s",
        thread="t",
        seq=2,
        data=HarnessSyncedData(
            action="skip",
            tasks_synced=0,
            task_count=2,
            tasks=[HarnessLedgerTaskWire(task_id="a", description="x", status="pending")],
        ),
    )
    parsed = event_adapter.validate_python(evt.model_dump())
    assert isinstance(parsed, HarnessSynced)
    assert parsed.data.action == "skip"
    assert len(parsed.data.tasks) == 1
