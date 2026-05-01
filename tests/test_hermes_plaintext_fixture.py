import copy
from pathlib import Path

import pytest

from hermes_plaintext_fixture import load_hermes_plaintext_fixture, safe_metrics


def test_load_hermes_plaintext_fixture_returns_payload_metadata_and_headers():
    fixture = load_hermes_plaintext_fixture(Path("tests/fixtures/hermes_plaintext_minimal.json"))

    assert fixture.payload["model"] == "gpt-test"
    assert fixture.metadata["source"] == "hermes-jsonl-plaintext"
    assert fixture.identity_headers == {"session_id": "sess_plaintext"}


def test_plaintext_fixture_rejects_encrypted_content_anywhere_under_input():
    data = copy.deepcopy(load_hermes_plaintext_fixture(Path("tests/fixtures/hermes_plaintext_minimal.json")).payload)
    data["input"][0]["content"][0]["encrypted_content"] = "ENCRYPTED"

    with pytest.raises(ValueError, match="encrypted_content"):
        safe_metrics(data)


def test_plaintext_fixture_rejects_compaction_items():
    data = copy.deepcopy(load_hermes_plaintext_fixture(Path("tests/fixtures/hermes_plaintext_minimal.json")).payload)
    data["input"].append({"type": "compaction", "summary": "not encrypted"})

    with pytest.raises(ValueError, match="compaction"):
        safe_metrics(data)


def test_plaintext_fixture_rejects_encrypted_content_outside_input():
    data = copy.deepcopy(load_hermes_plaintext_fixture(Path("tests/fixtures/hermes_plaintext_minimal.json")).payload)
    data["reasoning"] = {"effort": "medium", "encrypted_content": "ENCRYPTED"}

    with pytest.raises(ValueError, match="encrypted_content"):
        safe_metrics(data)


def test_safe_metrics_returns_counts_without_raw_text():
    fixture = load_hermes_plaintext_fixture(Path("tests/fixtures/hermes_plaintext_minimal.json"))

    metrics = safe_metrics(fixture.payload)

    assert metrics["input_items"] == 4
    assert metrics["response_item_types"] == {"message": 2, "function_call": 1, "function_call_output": 1}
    assert metrics["tools"] == 0
    assert metrics["forbidden_encrypted_fields"] == 0
    rendered = str(metrics)
    assert "private user request" not in rendered
    assert "private tool output" not in rendered
