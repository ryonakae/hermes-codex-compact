"""Authentication helpers for OpenAI API key and Hermes Codex OAuth modes."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

CODEX_DEFAULT_BASE_URL = "https://chatgpt.com/backend-api/codex"


def resolve_codex_credentials(resolver: Optional[Callable[[], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Resolve Codex OAuth runtime credentials via Hermes, never auth JSON files."""
    if resolver is None:
        from hermes_cli.auth import resolve_codex_runtime_credentials

        resolver = resolve_codex_runtime_credentials
    creds = resolver()
    token = creds.get("api_key")
    if not token:
        raise ValueError("Hermes openai-codex OAuth credentials did not provide an access token")
    return {
        "api_key": token,
        "base_url": creds.get("base_url") or CODEX_DEFAULT_BASE_URL,
        **{k: v for k, v in creds.items() if k not in {"api_key", "base_url"}},
    }


def build_codex_headers(
    access_token: str,
    header_builder: Optional[Callable[[str], Dict[str, str]]] = None,
) -> Dict[str, str]:
    """Build Codex backend headers using Hermes helper when available."""
    if header_builder is None:
        # Private Hermes helper. Acceptable for PoC; documented in README/AGENTS.
        from agent.auxiliary_client import _codex_cloudflare_headers

        header_builder = _codex_cloudflare_headers
    headers = dict(header_builder(access_token) or {})
    headers["Authorization"] = f"Bearer {access_token}"
    headers["Content-Type"] = "application/json"
    return headers
