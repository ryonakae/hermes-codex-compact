from client import CompactClient
from config import CodexCompactConfig


def test_codex_oauth_request_includes_identity_headers_from_config():
    config = CodexCompactConfig(
        auth_mode="codex_oauth",
        codex_session_id="sess_1",
        codex_window_id="sess_1:0",
        codex_installation_id="install_1",
    )
    client = CompactClient(
        config,
        codex_resolver=lambda: {"api_key": "token", "base_url": "https://example.test/codex"},
        codex_header_builder=lambda token: {"Authorization": f"Bearer {token}"},
    )

    url, headers = client._codex_oauth_request(compact=True)

    assert url == "https://example.test/codex/responses/compact"
    assert headers["session_id"] == "sess_1"
    assert headers["x-codex-window-id"] == "sess_1:0"
    assert headers["x-codex-installation-id"] == "install_1"


def test_api_key_request_does_not_add_codex_identity_headers():
    config = CodexCompactConfig(
        auth_mode="api_key",
        openai_api_key="sk-test",
        codex_session_id="sess_1",
        codex_window_id="sess_1:0",
        codex_installation_id="install_1",
    )
    client = CompactClient(config)

    _, headers = client._api_key_request(compact=True)

    assert "session_id" not in headers
    assert "x-codex-window-id" not in headers
    assert "x-codex-installation-id" not in headers
