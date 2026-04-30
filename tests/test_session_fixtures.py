import json
from pathlib import Path

import pytest

from engine import CodexCompactEngine
from session_fixtures import load_session_messages, summarize_messages


class FakeClient:
    def __init__(self):
        self.payloads = []

    def compact(self, payload):
        self.payloads.append(payload)
        return {"output_text": "Goal: evaluate real session compaction. Next: compare quality."}


def write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def test_load_session_messages_accepts_message_only_jsonl(tmp_path):
    fixture = tmp_path / "messages.jsonl"
    write_jsonl(
        fixture,
        [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "実セッションをcompressしたい"},
            {"role": "assistant", "content": "fixture loaderを作ります"},
        ],
    )

    messages = load_session_messages(fixture)

    assert [m["role"] for m in messages] == ["system", "user", "assistant"]
    assert messages[1]["content"] == "実セッションをcompressしたい"


def test_load_session_messages_accepts_wrapped_session_export_rows(tmp_path):
    fixture = tmp_path / "export.jsonl"
    write_jsonl(
        fixture,
        [
            {"type": "metadata", "session_id": "abc"},
            {"message": {"role": "user", "content": "hello"}},
            {"messages": [{"role": "assistant", "content": "hi"}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "terminal", "content": "ok"},
        ],
    )

    messages = load_session_messages(fixture)

    assert [m["role"] for m in messages] == ["user", "assistant", "tool"]
    assert messages[-1]["tool_call_id"] == "call_1"


def test_load_session_messages_rejects_fixture_without_messages(tmp_path):
    fixture = tmp_path / "empty.jsonl"
    write_jsonl(fixture, [{"type": "metadata"}])

    with pytest.raises(ValueError, match="No Hermes/OpenAI messages"):
        load_session_messages(fixture)


def test_real_session_fixture_can_drive_engine_with_fake_client():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"
    messages = load_session_messages(fixture)
    client = FakeClient()
    engine = CodexCompactEngine(client=client, recent_tail_messages=2)

    replacement = engine.compress(messages, current_tokens=900)

    assert client.payloads
    assert summarize_messages(messages)["messages"] >= 4
    assert any("Goal: evaluate real session compaction" in str(m.get("content", "")) for m in replacement)
    assert replacement[-1]["role"] == "user"


def test_private_real_session_fixture_is_opt_in():
    private_dir = Path(__file__).parent / "fixtures" / "private"
    private_fixture = next(private_dir.glob("*.jsonl"), None) if private_dir.exists() else None
    if not private_fixture:
        pytest.skip("no private real-session fixture present")

    import os

    if os.getenv("RUN_CODEX_COMPACT_PRIVATE") != "1":
        pytest.skip("private real-session fixture smoke requires RUN_CODEX_COMPACT_PRIVATE=1")

    messages = load_session_messages(private_fixture)
    client = FakeClient()
    engine = CodexCompactEngine(client=client, recent_tail_messages=4)
    replacement = engine.compress(messages, current_tokens=900)

    assert client.payloads
    assert summarize_messages(messages)["messages"] >= 1
    assert "Goal: evaluate real session compaction" in replacement[1]["content"]
