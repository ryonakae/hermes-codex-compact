from pathlib import Path

from session_fixtures import load_session_messages
from scripts.smoke_compact import (
    build_payload_from_fixture,
    dry_run_summary,
    evaluate_handoff_quality,
    variant_overrides,
)


def test_smoke_compact_builds_payload_from_fixture():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"

    payload, messages = build_payload_from_fixture(fixture, model="gpt-test", focus_topic="履歴圧縮")

    assert payload["model"] == "gpt-test"
    assert payload["input"][0]["type"] == "message"
    assert len(messages) == len(load_session_messages(fixture))
    assert "実際のセッション履歴" in str(payload["input"])


def test_dry_run_summary_includes_replacement_preview_without_raw_response():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"
    payload, messages = build_payload_from_fixture(fixture, model="gpt-test", focus_topic=None)

    summary = dry_run_summary(payload, messages, fixture=fixture, compare_builtin=False)

    assert summary["dry_run"] is True
    assert summary["fixture"].endswith("synthetic_session.jsonl")
    assert summary["message_summary"]["messages"] >= 4
    assert summary["payload_summary"]["input_items"] == len(payload["input"])
    assert summary["payload_summary"]["response_item_types"]["message"] >= 1
    assert "replacement_preview" in summary
    assert "raw_response" not in summary


def test_variant_overrides_map_to_codex_parity_settings():
    conversion = variant_overrides("conversion-parity")
    assert conversion["message_shape"] == "core"

    payload = variant_overrides("payload-parity")
    assert payload["instruction_policy"] == "codex_base_only"

    preprocessing = variant_overrides("preprocessing-parity")
    assert preprocessing["missing_tool_output_policy"] == "aborted"
    assert preprocessing["preprocessing_mode"] == "codex_parity"
    assert preprocessing["recent_tail_messages"] == 0

    instructed = variant_overrides("instructed-remote")
    assert instructed["message_shape"] == "core"
    assert instructed["instruction_policy"] == "codex_base_only"
    assert instructed["parallel_tool_calls"] is True
    assert instructed["base_instructions"]


def test_instructed_remote_fixture_payload_has_non_empty_instructions():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"

    payload, _messages = build_payload_from_fixture(
        fixture,
        model="gpt-test",
        focus_topic=None,
        variant="instructed-remote",
    )

    assert len(payload["instructions"]) > 0
    assert payload["parallel_tool_calls"] is True


def test_instructed_tools_remote_fixture_payload_has_tool_schemas():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"

    payload, _messages = build_payload_from_fixture(
        fixture,
        model="gpt-test",
        focus_topic=None,
        variant="instructed-tools-remote",
    )

    assert len(payload["instructions"]) > 0
    assert payload["parallel_tool_calls"] is True
    assert len(payload["tools"]) > 0
    assert {tool["name"] for tool in payload["tools"]} >= {"write_file"}


def test_smoke_payload_variant_changes_message_shape():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"

    payload, _messages = build_payload_from_fixture(
        fixture,
        model="gpt-test",
        focus_topic=None,
        variant="conversion-parity",
    )

    assert payload["input"][0].get("type") != "message"
    assert payload["input"][0]["role"] == "user"


def test_handoff_quality_metrics_detect_key_sections():
    text = """
    ## Active Task
    Implement parity.
    ## Completed Actions
    Added tests.
    ## Remaining Work
    Run smoke.
    commit 1234567
    """

    metrics = evaluate_handoff_quality(text)

    assert metrics["has_active_task"] is True
    assert metrics["has_completed_actions"] is True
    assert metrics["has_remaining_work"] is True
    assert metrics["mentions_commit"] is True
    assert metrics["likely_resumable"] is True


def test_handoff_quality_detects_raw_tool_dump():
    metrics = evaluate_handoff_quality("skill_view output " + "x" * 10000)
    assert metrics["raw_tool_dump_detected"] is True
    assert metrics["skill_view_dump_detected"] is True
