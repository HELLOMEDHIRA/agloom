"""Pattern handlers: one `handle_*` entry point per orchestration style (ReAct, swarm, DAG, etc.)."""

from .blackboard import handle_blackboard
from .hybrid_dag import handle_hybrid_dag
from .pipeline import handle_pipeline
from .planner_executor import handle_planner_executor
from .react import handle_react
from .reflection import handle_reflection
from .supervisor import handle_supervisor
from .swarm import handle_swarm

__all__ = [
    "handle_blackboard",
    "handle_hybrid_dag",
    "handle_pipeline",
    "handle_planner_executor",
    "handle_react",
    "handle_reflection",
    "handle_supervisor",
    "handle_swarm",
]
