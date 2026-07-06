"""Public API exports."""

from agloom import Signal, SignalType


def test_signal_exported_from_package_root() -> None:
    assert Signal is not None
    assert SignalType.HALT_ALL.value == "HALT_ALL"
