"""AgentConfig validation and frozen helpers."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from agloom.frozen import validate_frozen_params
from agloom.models import AgentConfig, PatternType, QueryAnalysis, SubTask
from agloom.frozen import analysis_for_turn


def test_valid_config_passes() -> None:
    cfg = AgentConfig(model="openai:gpt-4o")
    assert cfg.model == "openai:gpt-4o"


def test_agent_config_session_max_turns_default_matches_create_agent() -> None:
    assert AgentConfig(model="openai:gpt-4o-mini").session_max_turns == 50


def test_rejects_invalid_agent_config() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(model=cast("Any", None))
    with pytest.raises(ValidationError):
        AgentConfig(model="  ")
    with pytest.raises(ValidationError):
        AgentConfig(model="m", name="")
    with pytest.raises(ValidationError):
        AgentConfig(model="m", interrupt_before=["FAKE"])
    with pytest.raises(ValidationError):
        AgentConfig(model="m", user_callback="not_fn")
    with pytest.raises(ValidationError):
        AgentConfig(model="m", max_concurrent=cast("Any", 0))
    with pytest.raises(ValidationError):
        AgentConfig(model="m", max_concurrent=cast("Any", 33))
    with pytest.raises(ValidationError):
        AgentConfig(model="m", max_retries=cast("Any", 11))


def test_frozen_params_noop() -> None:
    validate_frozen_params(False)
    validate_frozen_params(True)


def test_analysis_for_turn_substitutes_input_placeholder() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.DIRECT,
        complexity=1,
        reasoning="r",
        subtasks=[SubTask(worker_id="w1", task="Do {input}")],
    )
    updated = analysis_for_turn(analysis, "payload")
    assert updated.subtasks[0].task == "Do payload"
