from local_style_compact import build_local_style_payload, load_compact_templates


def test_load_compact_templates_contains_codex_checkpoint_prompt():
    templates = load_compact_templates()

    assert "CONTEXT CHECKPOINT COMPACTION" in templates["prompt"]
    assert "handoff summary" in templates["prompt"]
    assert templates["summary_prefix"].strip()


def test_build_local_style_payload_appends_compact_prompt_without_mutating_remote_payload():
    remote_payload = {
        "model": "gpt-test",
        "instructions": "base instructions",
        "input": [{"type": "message", "role": "user", "content": "do work"}],
        "tools": [],
        "parallel_tool_calls": True,
    }

    local_payload = build_local_style_payload(remote_payload)

    assert remote_payload["input"] == [{"type": "message", "role": "user", "content": "do work"}]
    assert local_payload["model"] == "gpt-test"
    assert local_payload["instructions"] == "base instructions"
    assert local_payload["store"] is False
    assert local_payload["stream"] is True
    assert local_payload["input"][:-1] == remote_payload["input"]
    assert local_payload["input"][-1]["role"] == "user"
    assert "CONTEXT CHECKPOINT COMPACTION" in local_payload["input"][-1]["content"]
    assert "Another language model" in local_payload["input"][-1]["content"]
