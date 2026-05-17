"""Consistent steps_taken helper."""

from agloom.patterns._steps_accounting import steps_taken_from_audit


def test_steps_taken_from_audit_empty_is_one() -> None:
    assert steps_taken_from_audit([]) == 1
    assert steps_taken_from_audit(None) == 1


def test_steps_taken_from_audit_counts() -> None:
    assert steps_taken_from_audit([object(), object()]) == 2
