from pathlib import Path

from session_fixtures import load_session_messages
from scripts.smoke_compact import build_payload_from_fixture, dry_run_summary


def test_smoke_compact_builds_payload_from_fixture():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"

    payload, messages = build_payload_from_fixture(fixture, model="gpt-test", focus_topic="履歴圧縮")

    assert payload["model"] == "gpt-test"
    assert "Focus especially on: 履歴圧縮" in payload["instructions"]
    assert len(messages) == len(load_session_messages(fixture))
    assert any("実際のセッション履歴" in item["content"] for item in payload["input"])


def test_dry_run_summary_includes_replacement_preview_without_raw_response():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"
    payload, messages = build_payload_from_fixture(fixture, model="gpt-test", focus_topic=None)

    summary = dry_run_summary(payload, messages, fixture=fixture, compare_builtin=False)

    assert summary["dry_run"] is True
    assert summary["fixture"].endswith("synthetic_session.jsonl")
    assert summary["message_summary"]["messages"] >= 4
    assert summary["payload_summary"]["input_items"] == len(payload["input"])
    assert "replacement_preview" in summary
    assert "raw_response" not in summary
