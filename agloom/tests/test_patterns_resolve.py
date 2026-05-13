"""``patterns._resolve`` — worker system prompt defaults when agent config is sparse."""

from __future__ import annotations

from agloom.models import WorkerPlan
from agloom.patterns._resolve import resolve_worker_configs


def _agent(**kwargs):
    base = {
        "tools": [],
        "llm_timeout": 120.0,
        "max_retries": 2,
        "retry_delay": 1.0,
    }
    base.update(kwargs)
    return base


def test_resolve_defaults_when_system_prompt_none() -> None:
    agent = _agent(system_prompt=None)
    plans = [WorkerPlan(worker_id="w1", task="hi", system_instruction="", required_tools=[])]
    cfgs = resolve_worker_configs(agent, plans)
    assert cfgs[0].system_prompt == "You are a helpful AI assistant."


def test_resolve_defaults_when_system_prompt_whitespace() -> None:
    agent = _agent(system_prompt="   \n")
    plans = [WorkerPlan(worker_id="w1", task="hi", system_instruction="", required_tools=[])]
    cfgs = resolve_worker_configs(agent, plans)
    assert cfgs[0].system_prompt == "You are a helpful AI assistant."


def test_resolve_uses_subtask_instruction_over_default() -> None:
    agent = _agent(system_prompt=None)
    plans = [
        WorkerPlan(
            worker_id="w1",
            task="hi",
            system_instruction="  Be brief.  ",
            required_tools=[],
        )
    ]
    cfgs = resolve_worker_configs(agent, plans)
    assert cfgs[0].system_prompt == "Be brief."
