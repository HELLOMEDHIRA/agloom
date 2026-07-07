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
