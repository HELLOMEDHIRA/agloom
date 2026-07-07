"""Context Plane errors."""


class ContextBudgetExceededError(Exception):
    """Raised when message history cannot fit the input budget after compaction."""

    def __init__(self, *, estimated_tokens: int, budget: int, message: str | None = None) -> None:
        self.estimated_tokens = estimated_tokens
        self.budget = budget
        default = (
            f"Context budget exceeded after compaction; "
            f"estimated {estimated_tokens} tokens, budget {budget}"
        )
        super().__init__(message or default)
