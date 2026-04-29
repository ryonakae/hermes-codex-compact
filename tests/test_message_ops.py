from message_ops import (
    build_replacement_history,
    prepare_for_compact,
    sanitize_tail_tool_pairs,
)


def test_prepare_for_compact_truncates_long_tool_results_without_mutating_input():
    original = [{"role": "tool", "content": "x" * 20, "tool_call_id": "call_1"}]

    prepared = prepare_for_compact(original, max_tool_result_chars=5)

    assert prepared is not original
    assert prepared[0] is not original[0]
    assert len(prepared[0]["content"]) > 5
    assert "truncated" in prepared[0]["content"]
    assert original[0]["content"] == "x" * 20


def test_build_replacement_history_keeps_system_summary_and_safe_tail():
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "older"},
        {"role": "user", "content": "recent"},
    ]

    replacement = build_replacement_history(
        messages,
        compact_text="Summary here",
        recent_tail_messages=1,
    )

    assert replacement[0] == {"role": "system", "content": "rules"}
    assert replacement[1]["role"] == "user"
    assert "Context compacted by hermes-codex-compact" in replacement[1]["content"]
    assert "Summary here" in replacement[1]["content"]
    assert replacement[-1] == {"role": "user", "content": "recent"}


def test_build_replacement_history_does_not_duplicate_system_tail():
    messages = [{"role": "system", "content": "rules"}]

    replacement = build_replacement_history(messages, "Summary", recent_tail_messages=3)

    assert [m["role"] for m in replacement] == ["system", "user"]


def test_sanitize_tail_tool_pairs_drops_orphan_tool_result():
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "tool", "tool_call_id": "call_missing", "content": "orphan"},
        {"role": "user", "content": "continue"},
    ]

    sanitized = sanitize_tail_tool_pairs(messages)

    assert all(m.get("role") != "tool" for m in sanitized)
    assert sanitized[-1]["content"] == "continue"


def test_sanitize_tail_tool_pairs_keeps_complete_assistant_tool_pair():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
    ]

    sanitized = sanitize_tail_tool_pairs(messages)

    assert sanitized == messages


def test_sanitize_tail_tool_pairs_drops_assistant_tool_call_without_result():
    messages = [
        {"role": "user", "content": "before"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
        },
    ]

    sanitized = sanitize_tail_tool_pairs(messages)

    assert sanitized == [{"role": "user", "content": "before"}]
