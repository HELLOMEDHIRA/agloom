"""C8: ExecutionResult carries failure_class."""

from agloom.src.models import ExecutionResult, PatternType


def test_execution_result_failure_class_fields():
    r = ExecutionResult(
        pattern_used=PatternType.REACT,
        query="q",
        output="err",
        success=False,
        failure_class="transport",
        retryable=True,
    )
    assert r.failure_class == "transport"
    assert r.retryable is True


def test_failure_class_for_context_budget():
    from agloom.context.errors import ContextBudgetExceededError
    from agloom.patterns._failure import failure_class_for_error

    exc = ContextBudgetExceededError(estimated_tokens=90_000, budget=40_000)
    fc, retry = failure_class_for_error(str(exc), exc=exc)
    assert fc == "context"
    assert retry is False
