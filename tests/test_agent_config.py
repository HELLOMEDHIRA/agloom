"""AgentConfig validation and frozen-agent helpers."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from agloom.models import AgentConfig, PatternType, QueryAnalysis
from agloom.unified_agent import _apply_frozen_substitution, _validate_frozen_params


def test_valid_config_passes() -> None:
    cfg = AgentConfig(model="openai:gpt-4o")
    assert cfg.model == "openai:gpt-4o"


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


def test_max_retries_bounds() -> None:
    AgentConfig(model="m", max_retries=0)
    AgentConfig(model="m", max_retries=10)


def test_none_lists_normalized() -> None:
    assert AgentConfig(model="m", tools=cast("Any", None)).tools == []
    assert AgentConfig(model="m", middleware=cast("Any", None)).middleware == []
    assert AgentConfig(model="m", mcp_servers=cast("Any", None)).mcp_servers == []


def test_user_callback_and_interrupts() -> None:
    AgentConfig(model="m", user_callback=lambda: None)
    AgentConfig(model="m", interrupt_before=["DIRECT", "REACT"])


def test_frozen_requires_template() -> None:
    with pytest.raises(ValueError):
        _validate_frozen_params(True, "", "input")


def test_frozen_none_template_raises() -> None:
    with pytest.raises(ValueError):
        _validate_frozen_params(True, None, "input")


def test_frozen_empty_input_key_raises() -> None:
    with pytest.raises(ValueError):
        _validate_frozen_params(True, "t {input}", [])


def test_frozen_non_string_input_key_raises() -> None:
    with pytest.raises(ValueError):
        _validate_frozen_params(True, "t {x}", cast("Any", [123]))


def test_frozen_false_skips_validation() -> None:
    assert _validate_frozen_params(False, None, "") is None


def test_frozen_valid_params() -> None:
    assert _validate_frozen_params(True, "Classify: {input}", "input") is None


def test_apply_frozen_substitution_single_key() -> None:
    analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="r")
    q, sp, _a = _apply_frozen_substitution("hello", "Classify: {input}", "Sys: {input}", analysis, "input")
    assert q == "Classify: hello"
    assert sp == "Sys: hello"


def test_apply_frozen_substitution_multi_key() -> None:
    analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="r")
    q, _sp, _a = _apply_frozen_substitution(
        {"sender": "x", "body": "body text"},
        "From {sender}: {body}",
        "sys",
        analysis,
        ["sender", "body"],
    )
    assert q == "From x: body text"


def test_apply_frozen_substitution_missing_placeholder() -> None:
    analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="r")
    q, _sp, _a = _apply_frozen_substitution("val", "Template {missing}", "sys", analysis, "input")
    assert q == "Template {missing}"
