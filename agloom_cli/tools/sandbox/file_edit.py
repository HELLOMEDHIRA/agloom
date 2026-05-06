"""CRLF-aware search/replace helpers (aligned with DeepAgents sandbox edit semantics)."""

from __future__ import annotations


def match_edit_variants(old: str, new: str, text: str) -> tuple[str, str, int] | None:
    """Pick (old_variant, new_variant, count) for the first variant with count >= 1.

    Tries ``old`` as given, then CRLF-normalized, then LF-only, so models that send LF-only
    snippets still match CRLF files while preserving the file's line-ending style on write.
    """
    old_crlf = old.replace("\r\n", "\n").replace("\n", "\r\n")
    old_lf = old.replace("\r\n", "\n")
    new_crlf = new.replace("\r\n", "\n").replace("\n", "\r\n")
    new_lf = new.replace("\r\n", "\n")
    for cand_old, cand_new in ((old, new), (old_crlf, new_crlf), (old_lf, new_lf)):
        c = text.count(cand_old)
        if c >= 1:
            return cand_old, cand_new, c
    return None
