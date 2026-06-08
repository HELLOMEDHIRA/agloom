"""Consistent ``ExecutionResult.steps_taken`` across orchestration patterns."""

from __future__ import annotations


def steps_taken_from_audit(steps: list | None) -> int:
    """``steps_taken`` equals the audit trail length (``config['_steps']`` / ``AgentStep`` list).

    Every pattern should append to *steps* during execution and pass
    ``steps_taken=steps_taken_from_audit(steps)`` on the final ``ExecutionResult``.
  """
    if not steps:
        return 1
    return len(steps)
