from pathlib import Path

from codex_native_fixture import load_codex_native_fixture


def test_load_codex_native_fixture_preserves_encrypted_items():
    fixture = load_codex_native_fixture(Path("tests/fixtures/codex_native_minimal.json"))

    assert fixture.payload["model"] == "gpt-5.5"
    assert any(item["type"] == "reasoning" and item.get("encrypted_content") for item in fixture.payload["input"])
    assert any(item["type"] == "compaction" and item.get("encrypted_content") for item in fixture.payload["input"])


def test_load_codex_native_fixture_derives_identity_headers():
    fixture = load_codex_native_fixture(Path("tests/fixtures/codex_native_minimal.json"))

    assert fixture.identity_headers == {
        "session_id": "00000000-0000-4000-8000-000000000001",
        "x-codex-window-id": "00000000-0000-4000-8000-000000000001:0",
        "x-codex-installation-id": "00000000-0000-4000-8000-000000000002",
    }
