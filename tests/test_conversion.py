import json

from conversion import (
    COMPACT_INSTRUCTION_BASE,
    content_to_text,
    extract_compact_text,
    hermes_message_to_responses_input_item,
    hermes_messages_to_compact_payload,
    truncate_text,
)


def test_content_to_text_handles_strings_dicts_lists_and_none():
    assert content_to_text("hello") == "hello"
    assert '"a": 1' in content_to_text({"a": 1})
    assert "one" in content_to_text([{"type": "text", "text": "one"}])
    assert content_to_text(None) == ""


def test_content_to_text_replaces_image_like_parts_with_placeholder():
    text = content_to_text([
        {"type": "input_text", "text": "before"},
        {"type": "input_image", "image_url": "https://example.invalid/x.png"},
    ])

    assert "before" in text
    assert "[input_image omitted]" in text
    assert "example.invalid" not in text


def test_truncate_text_marks_omitted_characters():
    result = truncate_text("abcdef", 4)

    assert result.startswith("abcd")
    assert "truncated" in result


def test_hermes_message_to_responses_input_item_flattens_roles():
    assert hermes_message_to_responses_input_item({"role": "user", "content": "hi"}) == {
        "role": "user",
        "content": "hi",
    }

    assistant = hermes_message_to_responses_input_item({
        "role": "assistant",
        "content": "I will check",
        "tool_calls": [{"function": {"name": "terminal", "arguments": "{}"}}],
    })
    assert assistant["role"] == "assistant"
    assert "I will check" in assistant["content"]
    assert "Assistant requested tool calls" in assistant["content"]
    assert "terminal" in assistant["content"]

    tool = hermes_message_to_responses_input_item({
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "terminal",
        "content": "ok",
    })
    assert tool["role"] == "user"
    assert "[Tool result: terminal / call_1]" in tool["content"]

    system = hermes_message_to_responses_input_item({"role": "system", "content": "rules"})
    assert system["role"] == "user"
    assert "[System context]" in system["content"]


def test_hermes_messages_to_compact_payload_includes_instruction_focus_and_model():
    payload = hermes_messages_to_compact_payload(
        [{"role": "user", "content": "Build the plugin"}],
        model="gpt-test",
        focus_topic="auth",
    )

    assert payload["model"] == "gpt-test"
    assert payload["input"] == [{"role": "user", "content": "Build the plugin"}]
    assert COMPACT_INSTRUCTION_BASE in payload["instructions"]
    assert "Focus especially on: auth" in payload["instructions"]


def test_extract_compact_text_supports_output_text_and_output_items():
    assert extract_compact_text({"output_text": "summary"}) == "summary"

    response = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
            {"type": "message", "content": [{"type": "text", "text": "world"}]},
        ]
    }
    assert extract_compact_text(response) == "hello\nworld"


def test_extract_compact_text_rejects_unknown_shape():
    try:
        extract_compact_text({"output": []})
    except ValueError as exc:
        assert "Could not extract" in str(exc)
    else:
        raise AssertionError("expected ValueError")
