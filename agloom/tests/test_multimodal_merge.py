"""Multimodal merge and content normalization."""

from agloom.multimodal import content_blocks_to_text, merge_context_into_user_turn


def test_content_blocks_to_text_extracts_anthropic_blocks() -> None:
    text = content_blocks_to_text([{"type": "text", "text": "hello"}])
    assert text == "hello"


def test_merge_context_preserves_images_from_dict_turn() -> None:
    original = {
        "type": "text",
        "text": "see image",
        "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}],
    }
    merged = merge_context_into_user_turn("augmented query", original)
    assert isinstance(merged, list)
    assert merged[0]["type"] == "text"
    assert merged[0]["text"] == "augmented query"
    assert any(b.get("type") == "image_url" for b in merged[1:])
