"""Reflection pattern — iterative generate → critique → revise loop until quality threshold."""

import re

from .. import worker as worker_module
from ..logging_utils import get_logger
from ..models import (
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    SignalType,
    StepType,
    WorkerPlan,
    WorkerResult,
    _make_step,
    _merge_token_usage,
    _trunc,
)
from ..worker import extend_invoke_config_with_event_queue
from ._resolve import resolve_worker_configs
from .worker_gates import drain_for_halt, get_signal_queue

logger = get_logger(__name__)

GENERATOR_SYSTEM_PROMPT = """\
You are a thoughtful, high-quality content generator.
Your goal is to produce the best possible response to the user's task.
Be thorough, clear, and well-structured."""

REVISION_SYSTEM_PROMPT = """\
You are a thoughtful, high-quality content generator revising a previous draft.
You will receive the original goal, the previous draft, and specific feedback.
Address EVERY feedback point.  Improve quality, depth, and clarity."""

CRITIC_SYSTEM_PROMPT = """\
You are a rigorous quality critic.  Evaluate the draft response to the goal below.

Respond in EXACTLY this format (no extra lines before SCORE):
SCORE: <integer 1-10>
PASSED: <yes|no>
FEEDBACK: <specific, actionable critique — 2-4 sentences>

Rules:
- SCORE: integer from 1 to 10 (10 = perfect, 1 = unusable)
- PASSED: yes if quality is acceptable, no if revision is needed
- FEEDBACK: concrete improvements — never vague praise or blame"""


async def handle_reflection(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Generate → critique → revise loop. Each iteration produces a draft,
    scores it against a quality threshold, and revises with feedback.
    L4 HALT_ALL checked between iterations (not mid-generate/critique).
    """
    agent_name = agent.get("name", "Agent")
    llm = agent["llm"]
    ml = agent.get("max_step_output_length", 0)
    max_iterations = agent.get("max_reflection_iterations", 3)
    quality_threshold = agent.get("reflection_threshold", 7)
    signal_queue = get_signal_queue(agent, config)
    steps: list = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    raw_messages: list = []

    logger.event(
        f"[Reflection] {agent_name} — query={query[:60]}... max_iter={max_iterations}, threshold={quality_threshold}/10"
    )

    if not analysis.subtasks:
        logger.warning(f"[Reflection] {agent_name} — no subtasks, returning empty.")
        return ExecutionResult(
            pattern_used=PatternType.REFLECTION,
            query=query,
            output="No reflection goal could be determined for this query.",
            steps_taken=1,
            success=False,
            analysis=analysis,
            steps=steps,
            messages=raw_messages,
        )

    goal = analysis.subtasks[0].task
    required_tools = analysis.subtasks[0].required_tools

    best_draft: str = ""
    best_score: int = 0
    feedback: str = ""
    worker_results: list[WorkerResult] = []

    for iteration in range(max_iterations):
        if iteration > 0 and signal_queue:
            halt = await drain_for_halt(
                signal_queue,
                caller_name=f"{agent_name}[Reflection]",
            )
            if halt:
                logger.warning(
                    f"[Reflection] {agent_name} — HALT_ALL at iteration {iteration}. "
                    f"Returning best draft (score={best_score}/10)."
                )
                return ExecutionResult(
                    pattern_used=PatternType.REFLECTION,
                    query=query,
                    output=(best_draft or f"Halted before completion (HALT_ALL at iteration {iteration})."),
                    steps_taken=len(worker_results) + 1,
                    success=False,
                    analysis=analysis,
                    worker_results=worker_results,
                    error="HALT_ALL",
                    messages=raw_messages,
                )

        if iteration == 0:
            gen_task = goal
            gen_sys_prompt = GENERATOR_SYSTEM_PROMPT
        else:
            gen_task = (
                f"Revise and improve your previous response based on the "
                f"following expert feedback.\n\n"
                f"ORIGINAL GOAL:\n{goal}\n\n"
                f"PREVIOUS DRAFT:\n{best_draft}\n\n"
                f"FEEDBACK TO ADDRESS:\n{feedback}"
            )
            gen_sys_prompt = REVISION_SYSTEM_PROMPT

        gen_plan = WorkerPlan(
            worker_id=f"generator_{iteration}",
            task=gen_task,
            system_instruction=gen_sys_prompt,
            required_tools=required_tools,
            depends_on=[],
            context={},
        )
        gen_cfg = resolve_worker_configs(agent, [gen_plan])[0]

        logger.event(f"[Reflection] {agent_name} — iteration {iteration + 1}/{max_iterations}: generating...")
        merged = extend_invoke_config_with_event_queue(config, agent.get("_event_queue"), agent=agent)
        gen_result = await worker_module.run_worker(gen_cfg, llm, invoke_config=merged)
        worker_results.append(gen_result)
        raw_messages.extend(getattr(gen_result, "messages", []))
        steps.append(
            _make_step(
                StepType.WORKER_END,
                gen_result.worker_id,
                input=gen_result.task,
                output=gen_result.output,
                duration_ms=gen_result.elapsed_ms,
                signal=gen_result.signal.value,
                max_length=ml,
            )
        )
        if gen_result.token_usage:
            usage = _merge_token_usage(usage, gen_result.token_usage)

        if gen_result.signal == SignalType.FAILED:
            logger.error(f"[Reflection] Generator failed at iteration {iteration}: {gen_result.error}")
            if not best_draft:
                best_draft = gen_result.output or "Generation failed."
            break

        draft = gen_result.output
        critic_plan = WorkerPlan(
            worker_id=f"critic_{iteration}",
            task=(f"GOAL:\n{goal}\n\nDRAFT RESPONSE TO EVALUATE:\n{draft}"),
            system_instruction=CRITIC_SYSTEM_PROMPT,
            required_tools=[],  # critic evaluates text only
            depends_on=[],
            context={},
        )
        critic_cfg = resolve_worker_configs(agent, [critic_plan])[0]

        logger.event(f"[Reflection] {agent_name} — iteration {iteration + 1}/{max_iterations}: critiquing...")
        critic_result = await worker_module.run_worker(critic_cfg, llm, invoke_config=merged)
        worker_results.append(critic_result)
        raw_messages.extend(getattr(critic_result, "messages", []))
        if critic_result.token_usage:
            usage = _merge_token_usage(usage, critic_result.token_usage)

        parsed = _parse_critic_response(critic_result.output, quality_threshold)
        current_score = parsed["score"]
        feedback = parsed["feedback"]

        if current_score >= best_score:
            best_draft = draft
            best_score = current_score

        steps.append(
            _make_step(
                StepType.REFLECTION,
                f"critic_{iteration}",
                output=f"score={current_score}/10 passed={parsed['passed']}",
                duration_ms=critic_result.elapsed_ms,
                feedback=_trunc(feedback, ml),
            )
        )

        logger.event(
            f"[Reflection] {agent_name} — "
            f"iteration {iteration + 1} result: "
            f"score={current_score}/10, passed={parsed['passed']}, "
            f"feedback='{feedback[:80]}...'"
        )

        if current_score >= quality_threshold:
            logger.event(
                f"[Reflection] {agent_name} — "
                f"quality threshold met ({current_score}>={quality_threshold}) "
                f"after {iteration + 1} iteration(s)."
            )
            return ExecutionResult(
                pattern_used=PatternType.REFLECTION,
                query=query,
                output=best_draft,
                steps_taken=len(worker_results),
                success=True,
                analysis=analysis,
                worker_results=worker_results,
                metadata={
                    "final_score": best_score,
                    "iterations": iteration + 1,
                },
                steps=steps,
                token_usage=usage,
                messages=raw_messages,
            )

    logger.warning(f"[Reflection] ⚠ Max iterations reached — returning best draft (score={best_score}/10).")
    return ExecutionResult(
        pattern_used=PatternType.REFLECTION,
        query=query,
        output=best_draft or "Reflection failed to produce a valid draft.",
        steps_taken=len(worker_results),
        success=False,
        analysis=analysis,
        worker_results=worker_results,
        metadata={
            "final_score": best_score,
            "iterations": max_iterations,
        },
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )


def _parse_critic_response(text: str, threshold: int) -> dict:
    """Parse SCORE/PASSED/FEEDBACK from critic text. Falls back to safe defaults on garbled input."""
    try:
        score: int = 0
        passed: bool | None = None

        score_match = re.search(r"SCORE\s*:\s*(\d+)", text, re.IGNORECASE)
        if score_match:
            score = max(0, min(10, int(score_match.group(1))))

        passed_match = re.search(r"PASSED\s*:\s*(yes|no|true|false)", text, re.IGNORECASE)
        if passed_match:
            passed = passed_match.group(1).lower() in ("yes", "true")

        feedback_match = re.search(
            r"FEEDBACK\s*:\s*(.+?)(?=\n[A-Z]+\s*:|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        feedback = feedback_match.group(1).strip() if feedback_match else text.strip()

        if passed is None:
            passed = score >= threshold  # inclusive: threshold counts as pass

        return {"score": score, "passed": passed, "feedback": feedback}

    except Exception:
        return {"score": 5, "passed": False, "feedback": text}
