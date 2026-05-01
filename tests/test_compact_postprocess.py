import pytest

from compact_postprocess import (
    OpaqueRemoteCompactionError,
    compact_response_to_hermes_messages,
    response_item_to_hermes_message,
    should_keep_compacted_response_item,
)


def test_structured_output_messages_convert_to_hermes_messages():
    response = {
        "output": [
            {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "stale dev"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "summary"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "ok"}]},
            {"type": "function_call", "call_id": "call_1", "name": "terminal", "arguments": "{}"},
        ]
    }

    messages = compact_response_to_hermes_messages(response, original_messages=[])

    assert messages == [
        {"role": "user", "content": "summary"},
        {"role": "assistant", "content": "ok"},
    ]


def test_output_text_fallback_wraps_checkpoint_message():
    response = {"output_text": "Goal and next steps"}

    messages = compact_response_to_hermes_messages(response, original_messages=[])

    assert messages[0]["role"] == "user"
    assert "Context compacted by hermes-codex-compact" in messages[0]["content"]
    assert "Goal and next steps" in messages[0]["content"]


def test_nested_output_content_text_is_extracted():
    response = {"output": [{"content": [{"type": "output_text", "text": "nested summary"}]}]}

    messages = compact_response_to_hermes_messages(response, original_messages=[])

    assert "nested summary" in messages[0]["content"]


def test_response_item_to_hermes_message_joins_text_parts():
    item = {
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "output_text", "text": "one"},
            {"type": "output_text", "text": "two"},
        ],
    }

    assert response_item_to_hermes_message(item) == {"role": "assistant", "content": "one\ntwo"}


def test_should_keep_compacted_response_item_filters_codex_like_noise():
    assert should_keep_compacted_response_item({"type": "message", "role": "developer", "content": []}) is False
    assert should_keep_compacted_response_item({"type": "function_call", "call_id": "call_1"}) is False
    assert should_keep_compacted_response_item({"type": "message", "role": "assistant", "content": []}) is True
    assert should_keep_compacted_response_item({"type": "message", "role": "user", "content": []}) is True


def test_encrypted_only_compaction_is_opaque_not_readable_summary():
    item = {"type": "compaction", "encrypted_content": "ENCRYPTED_COMPACTION_SUMMARY"}

    assert should_keep_compacted_response_item(item) is False
    assert response_item_to_hermes_message(item) is None


def test_remote_compact_encrypted_only_response_fails_closed():
    response = {
        "output": [
            {"type": "compaction", "encrypted_content": "ENCRYPTED_COMPACTION_SUMMARY"},
        ]
    }

    with pytest.raises(OpaqueRemoteCompactionError) as exc:
        compact_response_to_hermes_messages(response, original_messages=[])

    assert "opaque Codex compaction checkpoint" in str(exc.value)
    assert "encrypted_content" in str(exc.value)


def test_remote_compact_encrypted_only_compaction_summary_fails_closed():
    response = {
        "output": [
            {"type": "compaction_summary", "encrypted_content": "ENCRYPTED_COMPACTION_SUMMARY"},
        ]
    }

    with pytest.raises(OpaqueRemoteCompactionError) as exc:
        compact_response_to_hermes_messages(response, original_messages=[])
    assert "ENCRYPTED_COMPACTION_SUMMARY" not in str(exc.value)


def test_recent_tail_is_appended_when_requested():
    response = {"output_text": "summary"}
    original = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "recent answer"},
        {"role": "user", "content": "latest request"},
    ]

    messages = compact_response_to_hermes_messages(response, original_messages=original, recent_tail_messages=1)

    assert messages[-1] == {"role": "user", "content": "latest request"}
