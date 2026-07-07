"""Context window budgeting and tool-result scratchpad (full fidelity off-thread)."""

from .plane import ContextBudget, assemble_memory_context, compute_context_budget
from .summarize import EpisodicSummary, episodic_summary_from_turns
from .tool_scratchpad import ToolScratchpad, build_tool_digest, make_recall_tool_artifact
from .tokens import count_tokens, estimate_messages_tokens
from .window import infer_context_window_tokens, reserved_output_tokens

__all__ = [
    "ContextBudget",
    "EpisodicSummary",
    "ToolScratchpad",
    "assemble_memory_context",
    "build_tool_digest",
    "compute_context_budget",
    "count_tokens",
    "episodic_summary_from_turns",
    "estimate_messages_tokens",
    "infer_context_window_tokens",
    "make_recall_tool_artifact",
    "reserved_output_tokens",
]
