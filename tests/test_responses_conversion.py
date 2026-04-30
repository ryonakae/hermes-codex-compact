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


def test_tool_call_id_pair_is_split_for_function_call_and_output():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_pair123|fc_pair123",
                "function": {"name": "terminal", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_pair123|fc_pair123", "content": "ok"},
    ]

    items, _ = hermes_messages_to_response_items(messages, drop_incomplete_tool_pairs=False)

    assert items[0]["call_id"] == "call_pair123"
    assert items[1]["call_id"] == "call_pair123"


def test_fc_only_tool_id_derives_call_id():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "fc_abc123",
                "function": {"name": "terminal", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_abc123", "content": "ok"},
    ]

    items, _ = hermes_messages_to_response_items(messages, drop_incomplete_tool_pairs=False)

    assert items[0]["call_id"] == "call_abc123"


def test_codex_message_items_are_replayed_before_reconstructed_content():
    messages = [{
        "role": "assistant",
        "content": "fallback should not duplicate",
        "codex_message_items": [{
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "phase": "final_answer",
            "content": [{"type": "text", "text": "exact replay"}],
        }],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert items == [{
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "phase": "final_answer",
        "content": [{"type": "output_text", "text": "exact replay"}],
    }]


def test_invalid_codex_message_items_fall_back_to_assistant_content():
    messages = [{
        "role": "assistant",
        "content": "fallback",
        "codex_message_items": [{"type": "message", "role": "user", "content": []}],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert items[0]["role"] == "assistant"
    assert "fallback" in str(items[0]["content"])


def test_reasoning_replay_is_assistant_only():
    messages = [{
        "role": "user",
        "content": "hello",
        "codex_reasoning_items": [{"id": "r1", "type": "reasoning", "encrypted_content": "secret"}],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert all(item.get("type") != "reasoning" for item in items)


def test_reasoning_items_are_deduped_across_messages():
    reasoning = {"id": "r1", "type": "reasoning", "encrypted_content": "secret", "summary": []}
    messages = [
        {"role": "assistant", "content": "a", "codex_reasoning_items": [reasoning]},
        {"role": "assistant", "content": "b", "codex_reasoning_items": [reasoning]},
    ]

    items, _ = hermes_messages_to_response_items(messages)

    assert sum(1 for item in items if item.get("type") == "reasoning") == 1


def test_reasoning_only_assistant_gets_following_empty_message():
    messages = [{
        "role": "assistant",
        "content": "",
        "codex_reasoning_items": [{"id": "r1", "type": "reasoning", "encrypted_content": "secret"}],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert items[0]["type"] == "reasoning"
    assert items[1]["role"] == "assistant"


def test_core_like_message_shape_omits_type_for_normal_user_and_assistant():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    items, _ = hermes_messages_to_response_items(messages, message_shape="core")

    assert items == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_response_item_message_shape_remains_supported():
    messages = [{"role": "user", "content": "hello"}]

    items, _ = hermes_messages_to_response_items(messages, message_shape="response_item")

    assert items[0]["type"] == "message"


def test_codex_base_only_policy_keeps_developer_context_in_input():
    messages = [
        {"role": "system", "content": "base rules"},
        {"role": "developer", "content": "repo context"},
        {"role": "user", "content": "do it"},
    ]

    items, instructions = hermes_messages_to_response_items(
        messages,
        message_shape="core",
        instruction_policy="codex_base_only",
    )

    assert instructions == "base rules"
    assert {"role": "developer", "content": "repo context"} in items
