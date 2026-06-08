"""Hybrid DAG synthesis must use PH_* placeholders, not str.format."""

from agloom.patterns._synthesis_contract import PH_ORIGINAL_QUERY, PH_WORKER_OUTPUTS
from agloom.patterns.hybrid_dag import HYBRID_DAG_SYNTHESIS_PROMPT, human_message_body_replace_placeholders


def test_synthesis_prompt_substitutes_placeholders_with_json_in_outputs() -> None:
    outputs = '{"key": "{nested}"}'
    prompt = human_message_body_replace_placeholders(
        HYBRID_DAG_SYNTHESIS_PROMPT,
        {PH_ORIGINAL_QUERY: "What is X?", PH_WORKER_OUTPUTS: outputs},
    )
    assert PH_ORIGINAL_QUERY not in prompt
    assert PH_WORKER_OUTPUTS not in prompt
    assert "What is X?" in prompt
    assert outputs in prompt
