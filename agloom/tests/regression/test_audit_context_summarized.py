"""Context Plane summarization observability and ref preservation."""

from agloom.context.summarize import (
    _prepare_summarizer,
    refs_preserved_in_summary,
    summarize_oldest_turns_sync,
)


class _BindableSumm:
    def __init__(self) -> None:
        self.bound: dict | None = None

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def invoke(self, messages):
        class R:
            content = "summary with ref=abc12345"

        return R()


def test_prepare_summarizer_binds_temperature_zero():
    model = _BindableSumm()
    prepared = _prepare_summarizer(model)
    assert prepared is model
    assert model.bound == {"temperature": 0}


def test_refs_preserved_in_summary_detects_missing_ref():
    assert refs_preserved_in_summary(
        ["abc12345"],
        summary_text="summary with ref=abc12345",
        artifact_refs=["abc12345"],
    )
    assert not refs_preserved_in_summary(
        ["missingref"],
        summary_text="no refs here",
        artifact_refs=[],
    )


def test_episodic_summarize_emits_structured_summary_turn():
    turns = [{"q": f"q{i}", "a": f"a{i} ref=deadbeef12345678"} for i in range(6)]
    compressed, episodic = summarize_oldest_turns_sync(turns, summarizer_model=_BindableSumm())
    assert len(compressed) < len(turns)
    assert episodic is not None
    assert compressed[0]["q"] == "[SUMMARY]"
