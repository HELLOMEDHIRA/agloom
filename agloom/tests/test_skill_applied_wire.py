"""AGP skill.applied manifest preview on the wire."""

from __future__ import annotations

import asyncio

import pytest

from agloom.models import AgentEvent
from agloom.protocol.events import SkillAppliedData
from agloom.runtime.translator import translate
from agloom.skills.injector import SkillInjector, parse_skill_names_from_context
from agloom.tests.test_runtime_bridge import capture_emitter
from agloom.unified_agent import (
    _build_skill_context_for_classify,
    _emit_skill_context_event,
    _wire_context_preview,
)


def test_skill_applied_data_optional_fields_default() -> None:
    d = SkillAppliedData(phase="classifier", injected_chars=10)
    assert d.skills == []
    assert d.context_preview == ""
    assert d.truncated is False


def test_wire_context_preview_truncates() -> None:
    text = "x" * 9000
    preview, truncated = _wire_context_preview(text, max_chars=8192)
    assert len(preview) == 8192
    assert truncated is True


def test_parse_skill_names_from_context() -> None:
    ctx = "=== RELEVANT SKILLS ===\n  - [alert-rca]: RCA\n  - [slo-sli]: SLO\n==="
    assert parse_skill_names_from_context(ctx) == ["alert-rca", "slo-sli"]


@pytest.mark.asyncio
async def test_emit_skill_context_event_includes_manifest_fields() -> None:
    q: asyncio.Queue = asyncio.Queue()
    ctx = (
        "=== RELEVANT SKILLS ===\n"
        "  - [lint_python]: Lint Python\n"
        "IMPORTANT: matched_skill\n"
        "==="
    )
    config = {"_event_queue": q}
    await _emit_skill_context_event(config, ctx, ["lint_python"])

    evt = await q.get()
    assert evt.type == "skill_context"
    assert evt.data["skills"] == ["lint_python"]
    assert "lint_python" in evt.data["context_preview"]
    assert evt.data["injected_chars"] == len(ctx)
    assert evt.data["truncated"] is False


@pytest.mark.asyncio
async def test_legacy_injector_parses_skill_names_from_context() -> None:
    class _Injector:
        async def get_context(self, query: str) -> str:
            _ = query
            return "=== RELEVANT SKILLS ===\n  - [alert-rca]: Alert RCA\n==="

    ctx, names = await _build_skill_context_for_classify(
        {"skill_injector": _Injector()},
        processed_query="investigate alert",
    )
    assert names == ["alert-rca"]
    assert "alert-rca" in ctx


def test_skill_applied_data_accepts_legacy_skill_names() -> None:
    d = SkillAppliedData(phase="classifier", injected_chars=10, skill_names=["legacy-skill"])
    assert d.skills == ["legacy-skill"]


def test_translate_skill_context_passes_preview_to_emitter() -> None:
    em = capture_emitter()
    translate(
        AgentEvent(
            type="skill_context",
            data={
                "phase": "classifier",
                "injected_chars": 50,
                "skills": ["a"],
                "context_preview": "manifest line",
                "truncated": True,
            },
        ),
        em,
    )
    assert em.calls[0][1]["truncated"] is True
    assert em.calls[0][1]["context_preview"] == "manifest line"
    assert em.calls[0][1]["skills"] == ["a"]


@pytest.mark.asyncio
async def test_skill_injector_bundle_returns_names() -> None:
    class _Manifest:
        name = "deploy_checklist"

        def classifier_line(self) -> str:
            return f"  - [{self.name}]: Deploy steps"

    class _Registry:
        async def search_skills(self, *, query: str, top_k: int):
            _ = query, top_k
            return [_Manifest()]

    inj = SkillInjector(_Registry(), top_k=3)
    bundle = await inj.get_context_bundle("deploy app")
    assert bundle.skill_names == ["deploy_checklist"]
    assert "deploy_checklist" in bundle.context
