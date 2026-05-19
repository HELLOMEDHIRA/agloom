"""Frozen-agent execution plan: classify once, replay classifier-derived routing."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Literal

from .models import QueryAnalysis
from .orchestrator.plan import TurnOrchestrationPlan, resolve_turn_orchestration
from .turn_input import TurnInput

ExecutionMode = Literal["handler", "dispatch"]


@dataclass
class FrozenExecutionPlan:
    """Routing locked after the first frozen turn (classifier-derived)."""

    analysis: QueryAnalysis
    orchestration: TurnOrchestrationPlan
    execution_mode: ExecutionMode
    classify_text: str
    locked_at: float
    agent_fingerprint: str


def validate_frozen_params(frozen: bool) -> None:
    """Validate frozen-mode params at ``create_agent`` time."""
    return


def agent_fingerprint(config: dict[str, Any]) -> str:
    """Fingerprint for invalidating a frozen plan when agent wiring changes."""
    llm = config.get("llm")
    model_id = str(getattr(llm, "model_name", None) or getattr(llm, "model", None) or type(llm).__name__)
    tool_names = ",".join(sorted(getattr(t, "name", str(t)) for t in config.get("tools", [])))
    sp = str(config.get("system_prompt") or "")[:500]
    depth = str(config.get("max_pattern_depth", 0))
    raw = f"{model_id}|{tool_names}|{sp}|{depth}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def analysis_for_turn(analysis: QueryAnalysis, user_text: str) -> QueryAnalysis:
    """Use locked analysis; refresh subtask tasks that embed ``{input}`` placeholders."""
    if not analysis.subtasks or not user_text:
        return analysis
    updated = []
    any_changed = False
    for st in analysis.subtasks:
        task = st.task
        if "{input}" in task:
            any_changed = True
            task = task.replace("{input}", user_text)
        updated.append(st.model_copy(update={"task": task}))
    if not any_changed:
        return analysis
    return analysis.model_copy(update={"subtasks": updated})


def build_execution_plan(
    config: dict[str, Any],
    *,
    analysis: QueryAnalysis,
    handler: Any,
    classify_text: str,
    execution_mode: ExecutionMode,
) -> FrozenExecutionPlan:
    orch = resolve_turn_orchestration(config, analysis)
    plan = FrozenExecutionPlan(
        analysis=analysis,
        orchestration=orch,
        execution_mode=execution_mode,
        classify_text=classify_text,
        locked_at=time.monotonic(),
        agent_fingerprint=agent_fingerprint(config),
    )
    config["_frozen_plan"] = plan
    config["frozen_analysis"] = analysis
    config["_frozen_handler"] = handler
    config["_frozen_classify_text"] = classify_text
    config["_frozen_analysis_ts"] = plan.locked_at
    return plan


def get_frozen_plan(config: dict[str, Any]) -> FrozenExecutionPlan | None:
    plan = config.get("_frozen_plan")
    if isinstance(plan, FrozenExecutionPlan):
        if plan.agent_fingerprint != agent_fingerprint(config):
            clear_frozen_plan(config)
            return None
        return plan
    return None


def clear_frozen_plan(config: dict[str, Any]) -> None:
    config.pop("_frozen_plan", None)
    config["frozen_analysis"] = None
    config["_frozen_handler"] = None
    config["_frozen_classify_text"] = ""
    config["_frozen_analysis_ts"] = 0
    config["_frozen_replay"] = False


def classify_text_for_freeze(config: dict[str, Any], turn: TurnInput) -> str:
    stored = str(config.get("_frozen_classify_text") or "").strip()
    if stored:
        return stored
    text = turn.user_text.strip()
    if not text:
        raise ValueError("Frozen agent requires a non-empty user message on the first call.")
    config["_frozen_classify_text"] = text
    return text


def frozen_replay_active(config: dict[str, Any]) -> bool:
    return bool(config.get("frozen") and get_frozen_plan(config) is not None)


def apply_frozen_turn(
    config: dict[str, Any],
    turn: TurnInput,
) -> tuple[QueryAnalysis, Any, str, ExecutionMode, TurnOrchestrationPlan]:
    """Resolve locked routing and per-turn user text for replay."""
    plan = get_frozen_plan(config)
    if plan is None:
        raise RuntimeError("Frozen replay requested but no execution plan is locked.")
    analysis = analysis_for_turn(plan.analysis, turn.user_text)
    config["_frozen_replay"] = True
    return (
        analysis,
        config["_frozen_handler"],
        turn.user_text,
        plan.execution_mode,
        plan.orchestration,
    )
