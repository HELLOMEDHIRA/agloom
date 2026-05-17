from agloom.models import SignalType
from agloom.patterns._worker_signals import halted_worker_result, worker_execution_failed


def test_halted_worker_result_signal() -> None:
    r = halted_worker_result(worker_id="w", task="t", output="stopped")
    assert r.signal == SignalType.HALTED
    assert r.error == "HALT_ALL"


def test_worker_execution_failed_only_for_failed() -> None:
    assert worker_execution_failed(SignalType.FAILED)
    assert not worker_execution_failed(SignalType.HALTED)
    assert not worker_execution_failed(SignalType.SUCCESS)
