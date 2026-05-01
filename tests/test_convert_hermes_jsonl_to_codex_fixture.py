import json
from pathlib import Path

import pytest

from scripts.convert_hermes_jsonl_to_codex_fixture import build_fixture_document, main


def _write_jsonl(path: Path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_build_fixture_document_preserves_focus_tool_pair_and_bounds_output(tmp_path):
    source = tmp_path / "session.jsonl"
    _write_jsonl(
        source,
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "please compress this Hermes session"},
            {
                "role": "assistant",
                "content": "I will run tests",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "terminal", "arguments": "{\"command\": \"pytest -q\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_abc", "name": "terminal", "content": "x" * 20},
        ],
    )

    document = build_fixture_document(
        source,
        model="gpt-test",
        focus_topic="Hermes plaintext compact compatibility",
        max_tool_output_chars=5,
        recent_tail_messages=12,
    )

    payload = document["request"]
    assert document["metadata"]["source"] == "hermes-jsonl-plaintext"
    assert document["metadata"]["source_file"] == "session.jsonl"
    assert document["metadata"]["encrypted_content"] is False
    assert "Hermes plaintext compact compatibility" in payload["instructions"]
    assert "Recent Tail Priority" in payload["instructions"]
    assert "encrypted_content" not in json.dumps(payload["input"], ensure_ascii=False)
    assert any(item.get("type") == "function_call" and item.get("call_id") == "call_abc" for item in payload["input"])
    outputs = [item for item in payload["input"] if item.get("type") == "function_call_output"]
    assert outputs[0]["call_id"] == "call_abc"
    assert outputs[0]["output"].startswith("xxxxx")
    assert "truncated" in outputs[0]["output"]
    assert document["metadata"]["stats"]["truncated_tool_outputs"] == 1


def test_converter_refuses_public_output_without_override(tmp_path):
    source = tmp_path / "session.jsonl"
    _write_jsonl(source, [{"role": "user", "content": "hello"}])
    output = tmp_path / "public.json"

    with pytest.raises(SystemExit) as exc:
        main(["--input", str(source), "--output", str(output), "--model", "gpt-test"])

    assert exc.value.code == 2
    assert not output.exists()


def test_converter_writes_public_output_when_explicitly_allowed(tmp_path, capsys):
    source = tmp_path / "session.jsonl"
    _write_jsonl(source, [{"role": "user", "content": "hello"}])
    output = tmp_path / "public.json"

    code = main([
        "--input",
        str(source),
        "--output",
        str(output),
        "--model",
        "gpt-test",
        "--allow-public-output",
    ])

    assert code == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["request"]["model"] == "gpt-test"
    printed = capsys.readouterr().out
    assert "hello" not in printed
    assert "input_items" in printed
