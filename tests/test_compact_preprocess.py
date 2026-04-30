from compact_preprocess import (
    build_codex_compact_payload,
    estimate_response_item_visible_chars,
    response_item_type_counts,
)


def test_payload_uses_response_items_and_base_instructions():
    messages = [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "hello"},
    ]

    payload, stats = build_codex_compact_payload(messages, model="gpt-5.5")

    assert payload["model"] == "gpt-5.5"
    assert payload["instructions"] == "system rules"
    assert payload["input"][0]["type"] == "message"
    assert payload["tools"] == []
    assert payload["parallel_tool_calls"] is False
    assert stats["original_messages"] == 2
    assert stats["input_items"] == 1
    assert stats["response_item_types"] == {"message": 1}


def test_payload_accepts_tools_parallel_reasoning_and_text_controls():
    messages = [{"role": "user", "content": "hello"}]
    tools = [{"type": "function", "name": "terminal", "parameters": {"type": "object"}}]

    payload, _ = build_codex_compact_payload(
        messages,
        model="gpt-5.5",
        tools=tools,
        parallel_tool_calls=True,
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
    )

    assert payload["tools"] == tools
    assert payload["parallel_tool_calls"] is True
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["text"] == {"verbosity": "low"}


def test_preprocess_truncates_old_large_tool_outputs_before_latest_user():
    messages = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}], "content": ""},
        {"role": "tool", "tool_call_id": "call_1", "content": "x" * 10_000},
        {"role": "user", "content": "latest request must remain"},
    ]

    payload, stats = build_codex_compact_payload(
        messages,
        model="gpt-5.5",
        token_budget_chars=1000,
        max_tool_output_chars=100,
    )

    serialized = str(payload["input"])
    assert "latest request must remain" in serialized
    assert "truncated" in serialized
    assert stats["truncated_tool_outputs"] == 1
    assert stats["visible_chars"] <= 1000


def test_trim_removes_old_complete_tool_pairs_when_still_over_budget():
    messages = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}], "content": ""},
        {"role": "tool", "tool_call_id": "call_1", "content": "x" * 1000},
        {"role": "user", "content": "latest request must remain"},
    ]

    payload, stats = build_codex_compact_payload(
        messages,
        model="gpt-5.5",
        token_budget_chars=80,
        max_tool_output_chars=500,
    )

    serialized = str(payload["input"])
    assert "latest request must remain" in serialized
    assert "call_1" not in serialized
    assert stats["removed_tool_pairs"] == 1


def test_response_item_stats_count_types_and_visible_chars():
    items = [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]},
        {"type": "function_call", "call_id": "call_1", "name": "terminal", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "ok"},
    ]

    assert response_item_type_counts(items) == {"message": 1, "function_call": 1, "function_call_output": 1}
    assert estimate_response_item_visible_chars(items[0]) == len("hello")
