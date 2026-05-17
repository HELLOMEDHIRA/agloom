"""AGP wire contract: Python event models must expose keys clients rely on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agloom.protocol.events import (
    ErrorData,
    HITLDecisionData,
    HITLRequestData,
    MetricTokensData,
    OrchestrationStepData,
    PatternClassifiedData,
    TokenDeltaData,
    ToolCallErrorData,
    ToolCallResultData,
    ToolCallStartData,
    WorkerCompletedData,
    WorkerFailedData,
    WorkerHaltedData,
    WorkerSpawnedData,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "agp_wire_required_keys.json"

# Wire ``type`` → Pydantic ``data`` model (several types may share one model).
_PYTHON_MODELS_BY_EVENT: dict[str, type] = {
    "token.delta": TokenDeltaData,
    "metric.tokens": MetricTokensData,
    "orchestration.step": OrchestrationStepData,
    "pattern.classified": PatternClassifiedData,
    "error.fatal": ErrorData,
    "tool.call.start": ToolCallStartData,
    "tool.call.result": ToolCallResultData,
    "tool.call.error": ToolCallErrorData,
    "worker.spawned": WorkerSpawnedData,
    "worker.completed": WorkerCompletedData,
    "worker.failed": WorkerFailedData,
    "worker.halted": WorkerHaltedData,
    "hitl.request": HITLRequestData,
    "hitl.granted": HITLDecisionData,
    "hitl.denied": HITLDecisionData,
}


@pytest.fixture(scope="module")
def required_keys() -> dict[str, list[str]]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_contract_fixture_events_have_python_models(required_keys: dict[str, list[str]]) -> None:
    missing = set(required_keys) - set(_PYTHON_MODELS_BY_EVENT)
    assert not missing, f"fixture events without Python model mapping: {sorted(missing)}"


@pytest.mark.parametrize("event_type", list(_PYTHON_MODELS_BY_EVENT.keys()))
def test_python_models_expose_required_wire_keys(event_type: str, required_keys: dict[str, list[str]]) -> None:
    if event_type not in required_keys:
        pytest.skip(f"{event_type} not in contract fixture")
    model = _PYTHON_MODELS_BY_EVENT[event_type]
    fields = set(model.model_fields)
    for key in required_keys[event_type]:
        assert key in fields, f"{event_type}: missing model field {key!r} (have {sorted(fields)})"
