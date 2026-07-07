"""C1: injection must not tail-chop context."""

from agloom.memory import injection


def test_injection_module_no_tail_chop_in_source():
  src = open(injection.__file__, encoding="utf-8").read()
  assert "context[-max_chars:]" not in src
