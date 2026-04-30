from responses_conversion import (
    deterministic_call_id,
    hermes_messages_to_response_items,
    sanitize_response_tool_pairs,
)


def test_user_and_assistant_messages_become_response_message_items():
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    items, instructions = hermes_messages_to_response_items(messages)

    assert instructions == "rules"
    assert items == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]},
    ]


def test_assistant_tool_call_and_tool_result_become_function_items():
    messages = [
        {
            "role": "assistant",
            "content": "I will run it",
            "tool_calls": [{
                "id": "call_123",
                "type": "function",
                "function": {"name": "terminal", "arguments": "{\"command\": \"pwd\"}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_123", "name": "terminal", "content": "ok"},
    ]

    items, instructions = hermes_messages_to_response_items(messages)

    assert instructions == ""
    assert items[0] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "I will run it"}],
    }
    assert items[1] == {
        "type": "function_call",
        "call_id": "call_123",
        "name": "terminal",
        "arguments": "{\"command\": \"pwd\"}",
    }
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "call_123",
        "output": "ok",
    }


def test_list_content_uses_role_specific_text_part_types_and_omits_media_urls():
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "u"},
            {"type": "input_image", "image_url": "https://example.invalid/private.png"},
        ]},
        {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
    ]

    items, _ = hermes_messages_to_response_items(messages)

    assert items[0]["content"] == [
        {"type": "input_text", "text": "u"},
        {"type": "input_text", "text": "[input_image omitted]"},
    ]
    assert "example.invalid" not in str(items[0])
    assert items[1]["content"] == [{"type": "output_text", "text": "a"}]


def test_missing_tool_call_id_is_deterministic():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "terminal", "arguments": "{}"}}]},
    ]

    first, _ = hermes_messages_to_response_items(messages, drop_incomplete_tool_pairs=False)
    second, _ = hermes_messages_to_response_items(messages, drop_incomplete_tool_pairs=False)

    assert first[0]["type"] == "function_call"
    assert first[0]["call_id"].startswith("call_")
    assert first == second
    assert first[0]["call_id"] == deterministic_call_id("terminal", "{}", 0)


def test_orphan_function_call_output_is_removed():
    messages = [{"role": "tool", "tool_call_id": "call_missing", "content": "orphan"}]

    items, _ = hermes_messages_to_response_items(messages)

    assert items == []


def test_dangling_function_call_without_output_is_removed_when_requested():
    messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}]}]

    items, _ = hermes_messages_to_response_items(messages, drop_incomplete_tool_pairs=True)

    assert items == []


def test_complete_tool_pair_is_preserved_by_sanitizer():
    items = [
        {"type": "function_call", "call_id": "call_1", "name": "terminal", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "ok"},
    ]

    assert sanitize_response_tool_pairs(items, drop_incomplete_tool_pairs=True) == items


def test_codex_reasoning_items_replay_without_id():
    messages = [{
        "role": "assistant",
        "content": "done",
        "codex_reasoning_items": [{"id": "rs_1", "type": "reasoning", "encrypted_content": "secret", "summary": []}],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert items[0] == {"type": "reasoning", "encrypted_content": "secret", "summary": []}
    assert "id" not in items[0]
    assert items[1]["type"] == "message"
