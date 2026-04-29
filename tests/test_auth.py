from auth import build_codex_headers, resolve_codex_credentials


def test_resolve_codex_credentials_uses_injected_resolver():
    creds = resolve_codex_credentials(lambda: {"api_key": "token", "base_url": "https://example.invalid"})

    assert creds["api_key"] == "token"
    assert creds["base_url"] == "https://example.invalid"


def test_build_codex_headers_uses_injected_header_builder_and_adds_required_headers():
    headers = build_codex_headers("token", lambda token: {"ChatGPT-Account-ID": "acct"})

    assert headers["Authorization"] == "Bearer token"
    assert headers["Content-Type"] == "application/json"
    assert headers["ChatGPT-Account-ID"] == "acct"
