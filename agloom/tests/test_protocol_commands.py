"""Tests for the AGP typed command models and command_adapter."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agloom.protocol.commands import (
    Command,
    CommandCancel,
    CommandHITLRespond,
    CommandInvoke,
    CommandPing,
    CommandRuntimeShutdown,
    CommandSessionResume,
    CommandSubscribe,
    CommandToolInvoke,
    CommandWorkerAssign,
    command_adapter,
)


def _parse(raw: dict) -> Command:
    return command_adapter.validate_python(raw)


# ── CommandInvoke ──────────────────────────────────────────────────────────────


def test_invoke_minimal():
    cmd = _parse({"type": "command.invoke", "data": {"prompt": "hello"}})
    assert isinstance(cmd, CommandInvoke)
    assert cmd.data.prompt == "hello"
    assert cmd.data.thread is None


def test_invoke_with_thread():
    cmd = _parse({"type": "command.invoke", "data": {"prompt": "hi", "thread": "t_abc"}})
    assert isinstance(cmd, CommandInvoke)
    assert cmd.data.thread == "t_abc"


def test_invoke_extra_fields_tolerated():
    cmd = _parse({"type": "command.invoke", "data": {"prompt": "hi", "extra_future_field": 42}})
    assert isinstance(cmd, CommandInvoke)


def test_invoke_missing_prompt_raises():
    with pytest.raises(ValidationError):
        _parse({"type": "command.invoke", "data": {}})


# ── CommandCancel ──────────────────────────────────────────────────────────────


def test_cancel_no_data():
    cmd = _parse({"type": "command.cancel"})
    assert isinstance(cmd, CommandCancel)
    assert cmd.data.thread is None


def test_cancel_with_thread():
    cmd = _parse({"type": "command.cancel", "data": {"thread": "t_xyz"}})
    assert isinstance(cmd, CommandCancel)
    assert cmd.data.thread == "t_xyz"


def test_cancel_empty_data_dict():
    cmd = _parse({"type": "command.cancel", "data": {}})
    assert isinstance(cmd, CommandCancel)


# ── CommandHITLRespond ─────────────────────────────────────────────────────────


def test_hitl_respond_accept():
    cmd = _parse({"type": "command.hitl.respond", "data": {"request_id": "hr_1", "decision": "accept"}})
    assert isinstance(cmd, CommandHITLRespond)
    assert cmd.data.request_id == "hr_1"
    assert cmd.data.decision == "accept"


def test_hitl_respond_default_decision_reject():
    cmd = _parse({"type": "command.hitl.respond", "data": {"request_id": "hr_2"}})
    assert isinstance(cmd, CommandHITLRespond)
    assert cmd.data.decision == "reject"


def test_hitl_respond_with_text():
    cmd = _parse({"type": "command.hitl.respond", "data": {"request_id": "hr_3", "decision": "accept", "text": "yes please"}})
    assert isinstance(cmd, CommandHITLRespond)
    assert cmd.data.text == "yes please"  # narrowed by isinstance above


# ── CommandWorkerAssign ────────────────────────────────────────────────────────


def test_worker_assign_minimal():
    cmd = _parse({"type": "command.worker.assign", "data": {"worker_id": "w_1", "task": "analyse logs"}})
    assert isinstance(cmd, CommandWorkerAssign)
    assert cmd.data.worker_id == "w_1"
    assert cmd.data.task == "analyse logs"
    assert cmd.data.pattern is None
    assert cmd.data.tools == []


def test_worker_assign_full():
    cmd = _parse({
        "type": "command.worker.assign",
        "data": {
            "worker_id": "w_2",
            "task": "build report",
            "thread": "wt_abc",
            "parent_thread": "t_parent",
            "pattern": "REACT",
            "tools": ["read_file", "grep_files"],
        },
    })
    assert isinstance(cmd, CommandWorkerAssign)
    assert cmd.data.pattern == "REACT"
    assert "read_file" in cmd.data.tools


# ── CommandSessionResume ───────────────────────────────────────────────────────


def test_session_resume():
    cmd = _parse({"type": "command.session.resume", "data": {"thread": "t_old", "from_seq": 10}})
    assert isinstance(cmd, CommandSessionResume)
    assert cmd.data.thread == "t_old"
    assert cmd.data.from_seq == 10


def test_session_resume_no_from_seq():
    cmd = _parse({"type": "command.session.resume", "data": {"thread": "t_old"}})
    assert isinstance(cmd, CommandSessionResume)
    assert cmd.data.from_seq is None


# ── CommandRuntimeShutdown ─────────────────────────────────────────────────────


def test_runtime_shutdown():
    cmd = _parse({"type": "command.runtime.shutdown"})
    assert isinstance(cmd, CommandRuntimeShutdown)


def test_runtime_shutdown_with_data():
    cmd = _parse({"type": "command.runtime.shutdown", "data": {}})
    assert isinstance(cmd, CommandRuntimeShutdown)


# ── command.ping / subscribe / tool.invoke ────────────────────────────────────


def test_ping_optional_id():
    cmd = _parse({"type": "command.ping", "data": {"ping_id": "p1"}})
    assert isinstance(cmd, CommandPing)
    assert cmd.data.ping_id == "p1"


def test_subscribe_prefixes():
    cmd = _parse({"type": "command.subscribe", "data": {"prefixes": ["tool.", "thinking."]}})
    assert isinstance(cmd, CommandSubscribe)
    assert cmd.data.prefixes == ["tool.", "thinking."]


def test_tool_invoke():
    cmd = _parse({"type": "command.tool.invoke", "data": {"name": "echo", "arguments": {"x": 1}}})
    assert isinstance(cmd, CommandToolInvoke)
    assert cmd.data.name == "echo"
    assert cmd.data.arguments == {"x": 1}


# ── Unknown type raises ────────────────────────────────────────────────────────


def test_unknown_type_raises():
    with pytest.raises(ValidationError):
        _parse({"type": "command.unknown.xyz", "data": {}})


# ── JSON round-trip ────────────────────────────────────────────────────────────


def test_json_round_trip_invoke():
    raw = {"type": "command.invoke", "data": {"prompt": "hello", "thread": "t_1"}}
    cmd = _parse(raw)
    dumped = json.loads(cmd.model_dump_json())
    assert dumped["type"] == "command.invoke"
    assert dumped["data"]["prompt"] == "hello"
