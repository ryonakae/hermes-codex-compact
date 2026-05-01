from pathlib import Path

from codex_native_fixture import load_codex_native_fixture
from config import CodexCompactConfig
from compact_postprocess import OpaqueRemoteCompactionError
from session_fixtures import load_session_messages
from scripts.smoke_compact import (
    build_payload_from_codex_native_fixture,
    build_payload_from_fixture,
    build_payload_from_hermes_plaintext_fixture,
    compact_response_safe_summary,
    config_with_identity_headers,
    dry_run_summary,
    evaluate_handoff_quality,
    hermes_plaintext_dry_run_summary,
    main,
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


def test_focus_topic_is_reflected_as_compaction_context_not_raw_history():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"

    payload, _messages = build_payload_from_fixture(
        fixture,
        model="gpt-test",
        focus_topic="resume the Codex compact quality implementation",
        variant="instructed-tools-remote",
    )

    assert "resume the Codex compact quality implementation" in payload["instructions"]
    assert payload["input"][0].get("content") != "resume the Codex compact quality implementation"


def test_local_style_smoke_path_appends_compact_prompt():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"

    payload, _messages = build_payload_from_fixture(
        fixture,
        model="gpt-test",
        focus_topic=None,
        variant="instructed-tools-remote",
        compact_path="local-style",
    )

    assert "CONTEXT CHECKPOINT COMPACTION" in payload["input"][-1]["content"]
    assert payload["input"][-1]["role"] == "user"


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


def test_build_payload_from_codex_native_fixture_preserves_native_items():
    fixture = Path("tests/fixtures/codex_native_minimal.json")

    payload, stats, identity_headers = build_payload_from_codex_native_fixture(fixture)

    assert payload["model"] == "gpt-5.5"
    assert any(item["type"] == "reasoning" for item in payload["input"])
    assert any(item["type"] == "compaction" for item in payload["input"])
    assert stats["input_items"] == len(payload["input"])
    assert stats["codex_native_fixture"] is True
    assert identity_headers["session_id"]


def test_compact_response_safe_summary_detects_opaque_compaction():
    response = {"output": [{"type": "compaction", "encrypted_content": "ENCRYPTED"}]}
    summary = compact_response_safe_summary(response)
    assert summary["has_opaque_compaction"] is True


def test_compact_response_safe_summary_detects_opaque_compaction_summary():
    response = {"output": [{"type": "compaction_summary", "encrypted_content": "ENCRYPTED"}]}
    summary = compact_response_safe_summary(response)
    assert summary["has_opaque_compaction"] is True


def test_config_with_identity_headers_does_not_mutate_original_config():
    base = CodexCompactConfig(auth_mode="codex_oauth")
    fixture = load_codex_native_fixture(Path("tests/fixtures/codex_native_minimal.json"))

    updated = config_with_identity_headers(base, fixture.identity_headers)

    assert base.codex_session_id == ""
    assert updated.codex_session_id == fixture.identity_headers["session_id"]
    assert updated.codex_window_id == fixture.identity_headers["x-codex-window-id"]


def test_hermes_plaintext_fixture_dry_run_reports_safe_metrics_only():
    fixture = Path("tests/fixtures/hermes_plaintext_minimal.json")

    payload, metrics, identity_headers = build_payload_from_hermes_plaintext_fixture(fixture)
    summary = hermes_plaintext_dry_run_summary(payload, metrics, identity_headers, fixture=fixture)

    assert summary["hermes_plaintext_fixture"] is True
    assert summary["payload_summary"]["input_items"] == len(payload["input"])
    assert summary["payload_summary"]["forbidden_encrypted_fields"] == 0
    rendered = str(summary)
    assert "private user request" not in rendered
    assert "private tool output" not in rendered
    assert summary["identity_header_names"] == ["session_id"]


def test_plaintext_and_codex_native_fixtures_are_mutually_exclusive():
    code_args = [
        "--codex-native-fixture",
        "tests/fixtures/codex_native_minimal.json",
        "--hermes-plaintext-fixture",
        "tests/fixtures/hermes_plaintext_minimal.json",
    ]

    try:
        main(code_args)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


def test_hermes_plaintext_execute_passes_payload_to_client(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def __init__(self, config):
            captured["config"] = config

        def compact(self, payload):
            captured["payload"] = payload
            return {"output_text": "compact summary"}

    monkeypatch.setattr("scripts.smoke_compact.CompactClient", FakeClient)

    code = main([
        "--auth-mode",
        "codex_oauth",
        "--hermes-plaintext-fixture",
        "tests/fixtures/hermes_plaintext_minimal.json",
        "--execute",
    ])

    assert code == 0
    assert captured["payload"]["model"] == "gpt-test"
    assert captured["config"].codex_session_id == "sess_plaintext"
    printed = capsys.readouterr().out
    assert "compact summary" not in printed
    assert "response_summary" in printed


def test_hermes_plaintext_execute_fails_closed_on_opaque_compaction(monkeypatch):
    class FakeClient:
        def __init__(self, config):
            pass

        def compact(self, payload):
            return {"output": [{"type": "compaction", "encrypted_content": "ENCRYPTED"}]}

    monkeypatch.setattr("scripts.smoke_compact.CompactClient", FakeClient)

    try:
        main([
            "--auth-mode",
            "codex_oauth",
            "--hermes-plaintext-fixture",
            "tests/fixtures/hermes_plaintext_minimal.json",
            "--execute",
        ])
    except OpaqueRemoteCompactionError:
        pass
    else:
        raise AssertionError("expected OpaqueRemoteCompactionError")
