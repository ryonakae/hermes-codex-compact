from tool_schemas import extract_tool_names_from_messages, minimal_fixture_tool_schemas


def test_minimal_fixture_tool_schemas_returns_responses_compatible_tools():
    tools = minimal_fixture_tool_schemas(["terminal", "read_file", "unknown"])

    assert [tool["name"] for tool in tools] == ["terminal", "read_file"]
    assert all(tool["type"] == "function" for tool in tools)
    assert all(tool["description"] for tool in tools)
    assert all(tool["parameters"]["type"] == "object" for tool in tools)


def test_extract_tool_names_from_assistant_tool_calls_preserves_order():
    messages = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "terminal"}}]},
        {"role": "assistant", "tool_calls": [{"function": {"name": "read_file"}}]},
        {"role": "assistant", "tool_calls": [{"function": {"name": "terminal"}}]},
    ]

    assert extract_tool_names_from_messages(messages) == ["terminal", "read_file"]
