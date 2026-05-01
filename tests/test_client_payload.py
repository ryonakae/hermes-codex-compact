import json
import urllib.error

from config import CodexCompactConfig
from client import CompactClient, CompactHTTPError, redact_secret


def test_redact_secret_removes_bearer_tokens():
    token = "secret-token-123"
    text = f"Authorization: Bearer {token}"

    assert token not in redact_secret(text)
    assert "Bearer [REDACTED]" in redact_secret(text)


def test_redact_secret_removes_encrypted_content_error_fragments():
    text = "The encrypted content ENCR...ETIC could not be verified"

    redacted = redact_secret(text)

    assert "ENCR...ETIC" not in redacted
    assert "encrypted content [REDACTED]" in redacted


def test_api_key_request_uses_openai_endpoint_and_headers(monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers, timeout):
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {"output_text": "ok"}

    config = CodexCompactConfig(
        auth_mode="api_key",
        openai_api_key="sk-test",
        request_timeout_seconds=7,
    )
    client = CompactClient(config, post_json=fake_post_json)

    response = client.compact({"model": "gpt-test", "input": [], "instructions": "compact"})

    assert response == {"output_text": "ok"}
    assert captured["url"] == "https://api.openai.com/v1/responses/compact"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["timeout"] == 7


def test_api_key_request_reads_openai_api_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    captured = {}

    def fake_post_json(url, payload, headers, timeout):
        captured.update(headers=headers)
        return {"output_text": "ok"}

    client = CompactClient(CodexCompactConfig(auth_mode="api_key"), post_json=fake_post_json)
    client.compact({"model": "gpt-test", "input": [], "instructions": "compact"})

    assert captured["headers"]["Authorization"] == "Bearer sk-env"


def test_api_key_request_fails_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = CompactClient(CodexCompactConfig(auth_mode="api_key"), post_json=lambda *a, **k: {})

    try:
        client.compact({"model": "gpt-test", "input": [], "instructions": "compact"})
    except ValueError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_codex_oauth_request_uses_resolver_and_headers():
    captured = {}

    def fake_resolver():
        return {"api_key": "codex-token", "base_url": "https://chatgpt.com/backend-api/codex"}

    def fake_header_builder(token):
        assert token == "codex-token"
        return {"ChatGPT-Account-ID": "acct_1", "originator": "codex_cli_rs"}

    def fake_post_json(url, payload, headers, timeout):
        captured.update(url=url, headers=headers)
        return {"output_text": "ok"}

    client = CompactClient(
        CodexCompactConfig(auth_mode="codex_oauth"),
        post_json=fake_post_json,
        codex_resolver=fake_resolver,
        codex_header_builder=fake_header_builder,
    )
    client.compact({"model": "gpt-test", "input": [], "instructions": "compact"})

    assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses/compact"
    assert captured["headers"]["Authorization"] == "Bearer codex-token"
    assert captured["headers"]["ChatGPT-Account-ID"] == "acct_1"
    assert captured["headers"]["Content-Type"] == "application/json"


def test_http_error_redacts_authorization(monkeypatch):
    def fake_post_json(url, payload, headers, timeout):
        raise CompactHTTPError(401, "Authorization: Bearer very-secret")

    client = CompactClient(
        CodexCompactConfig(auth_mode="api_key", openai_api_key="sk-test"),
        post_json=fake_post_json,
    )

    try:
        client.compact({"model": "gpt-test", "input": [], "instructions": "compact"})
    except CompactHTTPError as exc:
        assert "very-secret" not in str(exc)
        assert "Bearer [REDACTED]" in str(exc)
    else:
        raise AssertionError("expected CompactHTTPError")
