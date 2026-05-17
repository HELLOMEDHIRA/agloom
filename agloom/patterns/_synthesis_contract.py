"""Cross-pattern synthesis outcomes and safe prompt assembly.

**Synthesis success rule** (multi-worker patterns that run a manager / synthesis LLM):
``ExecutionResult.success`` is True only when at least one sub-worker reported
``SignalType.SUCCESS`` *and* the synthesis LLM completed without falling back to
concatenated / degraded text.

**HALT semantics:** parallel patterns cancel in-flight tasks via
:func:`agloom.patterns.hitl._listen_for_halt`. Sequential runners
(:func:`agloom.patterns._sequential.run_sequential_workers`) only observe
``HALT_ALL`` between worker steps — there is no shared listener mid-step.

User-authored text (queries, worker outputs) must not be passed through
``str.format`` when the template also contains literal braces; use
:data:`PH_*` tokens and :func:`human_message_body_replace_placeholders`.
"""

from __future__ import annotations

from ..models import SignalType, WorkerResult

# Canonical ``ExecutionResult.error`` when no sub-task produced SUCCESS.
ALL_PATTERN_WORKERS_FAILED_ERROR = "AllPatternWorkersFailed"

# Stable template tokens (avoid ``str.format`` interpreting ``{...}`` inside user or worker text).
PH_ORIGINAL_QUERY = "__AGLOOM_ORIGINAL_QUERY__"
PH_WORKER_OUTPUTS = "__AGLOOM_WORKER_OUTPUTS__"
PH_AGENT_PERSPECTIVES = "__AGLOOM_AGENT_PERSPECTIVES__"


def any_worker_succeeded(worker_results: list[WorkerResult]) -> bool:
    return any(r.signal == SignalType.SUCCESS for r in worker_results)


def pattern_synthesis_success(*, worker_results: list[WorkerResult], synthesis_degraded: bool) -> bool:
    """Single cross-pattern rule for manager / synthesis LLM paths."""
    return any_worker_succeeded(worker_results) and not synthesis_degraded


def human_message_body_replace_placeholders(template: str, replacements: dict[str, str]) -> str:
    """Fill ``PH_*`` tokens without interpreting braces inside user or worker text."""
    out = template
    for key, val in replacements.items():
        out = out.replace(key, val)
    return out
