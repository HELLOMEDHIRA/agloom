"""REACT timeout and recursion helpers."""

from __future__ import annotations

from typing import Any

_AINVOKE_TIMEOUT = 120


def react_llm_timeout(agent: dict, config: dict | None = None) -> float:
    """Per model-call wall clock (honors ``exec_config`` then ``agent``)."""
    if config is not None:
        try:
            raw = config.get("llm_timeout")
            if raw is None:
                raw = agent.get("llm_timeout", _AINVOKE_TIMEOUT)
            return max(float(raw), 1.0)
        except (TypeError, ValueError):
            pass
    try:
        return max(float(agent.get("llm_timeout", _AINVOKE_TIMEOUT)), 1.0)
    except (TypeError, ValueError):
        return float(_AINVOKE_TIMEOUT)


def react_graph_wall_timeout(agent: dict, config: dict | None = None) -> float:
    """Wall clock for a full streamed ReAct graph (many model + tool rounds)."""
    explicit = agent.get("react_graph_timeout")
    if explicit is not None:
        try:
            return max(float(explicit), 1.0)
        except (TypeError, ValueError):
            pass
    base = react_llm_timeout(agent, config)
    return max(base * 4.0, 300.0)


def react_timeout_failure_message(
    agent: dict,
    *,
    wall_seconds: float,
    path: str,
    config: dict | None = None,
) -> str:
    llm_t = int(react_llm_timeout(agent, config))
    graph_t = int(react_graph_wall_timeout(agent, config))
    return (
        f"REACT timed out after {int(wall_seconds)}s ({path}). "
        f"Self-hosted inference with MCP tools often needs "
        f"create_agent(llm_timeout>={max(llm_t, 300)}, react_graph_timeout>={max(graph_t, 600)})."
    )


REACT_RECURSION_LIMIT = 25


def react_recursion_limit(agent: dict) -> int:
    raw = agent.get("react_recursion_limit", REACT_RECURSION_LIMIT)
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = REACT_RECURSION_LIMIT
    return max(1, min(limit, 500))


def react_recursion_limit_failure_message(*, limit: int, path: str) -> str:
    return (
        f"REACT step limit reached after {limit} graph steps ({path}). "
        "Investigation incomplete — simplify the task or raise create_agent(react_recursion_limit=…)."
    )


def react_retry_delay(attempt: int) -> float:
    return min(0.5 * (2 ** max(0, attempt - 1)), 8.0)
