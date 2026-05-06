"""Central hard caps for CLI tools and pathological HITL payloads.

Policy: **no silent truncation** — when a cap bites, tools use
:class:`~agloom_cli.tool_result_envelope.render_incomplete` (``[agloom:tool_result]`` … ``complete=false``)
plus explicit metrics, recovery hints, and often a **small preview** so the agent can plan the next
step without believing it saw the full payload. Pure ``Error:`` remains for invalid arguments /
transport failures. Bounded ``read_file`` windows still append a “more lines remain” footer.
"""

from __future__ import annotations

# --- read_file / grep_files (see agloom_cli.tools.filesystem) ---
READ_FILE_DEFAULT_MAX_BYTES = 1_048_576  # 1 MiB default per read
READ_FILE_ABS_MAX_BYTES = 10 * 1024 * 1024  # hard ceiling even if caller passes higher
READ_FILE_MAX_LINES_PER_CALL = 3000
READ_FILE_FULL_NO_LIMIT_MAX_LINES = 2000

GREP_MAX_FILE_BYTES = 2 * 1024 * 1024
GREP_MAX_MATCHES_DEFAULT = 200

# --- HTTP tools ---
HTTP_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
HTTP_MAX_BODY_CHARS = 500_000
HTTP_INCOMPLETE_PREVIEW_BYTES = 4096
HTTP_INCOMPLETE_PREVIEW_CHARS = 12_000

# --- fetch_json (shares HTTP response byte cap) ---
FETCH_JSON_INCOMPLETE_PREVIEW_CHARS = 12_000

# --- run_shell ---
RUN_SHELL_INCOMPLETE_PREVIEW_BYTES = 8192

# --- web_search ---
WEB_SEARCH_SNIPPET_MAX_CHARS = 4000
WEB_SEARCH_ANSWER_MAX_CHARS = 32_000
WEB_SEARCH_TOTAL_OUTPUT_MAX_CHARS = 250_000

RUN_SHELL_MAX_OUTPUT_BYTES = 1_048_576

# --- HITL triple-choice detail (pathological message guard only) ---
HITL_DETAIL_HARD_CAP_CHARS = 4_000_000


def clamp_hitl_detail(message: str) -> str:
    """Allow full interrupt text for normal use; cap only absurdly large payloads."""
    if len(message) <= HITL_DETAIL_HARD_CAP_CHARS:
        return message
    return (
        message[:HITL_DETAIL_HARD_CAP_CHARS]
        + "\n\n[agloom] Truncated: exceeded HITL_DETAIL_HARD_CAP_CHARS (pathological size guard)."
    )
