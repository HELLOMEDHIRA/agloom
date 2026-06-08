"""Windows-safe stdio writes for AGP NDJSON."""

from __future__ import annotations

import io
from typing import Any

from agloom.compat import safe_writer_write


class _Cp1252Writer:
  encoding = "cp1252"

  def __init__(self) -> None:
    self.buffer = io.BytesIO()

  def write(self, text: str) -> int:
    text.encode(self.encoding)
    return len(text)

  def flush(self) -> None:
    pass


def test_safe_writer_write_uses_binary_buffer_on_encode_error() -> None:
    w: Any = _Cp1252Writer()
    safe_writer_write(w, '{"output_preview":"\u2713 mkdir foo"}\n')
    assert b"mkdir foo" in w.buffer.getvalue()
