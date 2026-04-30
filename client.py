"""HTTP client for OpenAI/Codex compact endpoints."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

try:
    from .auth import build_codex_headers, resolve_codex_credentials
    from .config import CodexCompactConfig
except ImportError:  # pragma: no cover - local test fallback
    from auth import build_codex_headers, resolve_codex_credentials
    from config import CodexCompactConfig

_AUTH_RE = re.compile(r"Bearer\s+[^\s,;\n]+", re.IGNORECASE)


def redact_secret(text: str) -> str:
    return _AUTH_RE.sub("Bearer [REDACTED]", str(text))


class CompactHTTPError(RuntimeError):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = redact_secret(body)
        super().__init__(f"Compact API HTTP {status}: {self.body}")


def post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise CompactHTTPError(exc.code, body) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(redact_secret(str(exc))) from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        parsed = parse_sse_response(raw)
        if parsed is None:
            raise RuntimeError("Compact API returned non-JSON response") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Compact API returned a non-object JSON response")
    return parsed


def parse_sse_response(raw: str) -> Optional[Dict[str, Any]]:
    """Parse a small Responses SSE transcript into a response-like dict."""
    output_text_parts = []
    final_response: Optional[Dict[str, Any]] = None
    saw_sse = False
    for line in str(raw).splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        saw_sse = True
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if event_type.endswith("output_text.delta") and isinstance(event.get("delta"), str):
            output_text_parts.append(event["delta"])
        response = event.get("response")
        if event_type == "response.completed" and isinstance(response, dict):
            final_response = dict(response)
        elif isinstance(response, dict) and final_response is None:
            final_response = dict(response)
    if not saw_sse:
        return None
    output_text = "".join(output_text_parts)
    if final_response is None:
        final_response = {}
    if output_text and not final_response.get("output_text"):
        final_response["output_text"] = output_text
    return final_response


class CompactClient:
    """Small dependency-injectable client for compact smoke tests and engine use."""

    def __init__(
        self,
        config: CodexCompactConfig,
        *,
        post_json: Callable[[str, Dict[str, Any], Dict[str, str], int], Dict[str, Any]] = post_json,
        codex_resolver: Optional[Callable[[], Dict[str, Any]]] = None,
        codex_header_builder: Optional[Callable[[str], Dict[str, str]]] = None,
    ) -> None:
        self.config = config
        self._post_json = post_json
        self._codex_resolver = codex_resolver
        self._codex_header_builder = codex_header_builder

    def compact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(payload, compact=True)

    def responses(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(payload, compact=False)

    def _post(self, payload: Dict[str, Any], *, compact: bool) -> Dict[str, Any]:
        try:
            if self.config.auth_mode == "api_key":
                url, headers = self._api_key_request(compact=compact)
            elif self.config.auth_mode == "codex_oauth":
                url, headers = self._codex_oauth_request(compact=compact)
            elif self.config.auth_mode == "auto":
                url, headers = self._auto_request(compact=compact)
            else:
                raise ValueError(f"Unsupported auth_mode: {self.config.auth_mode}")
            return self._post_json(url, payload, headers, self.config.request_timeout_seconds)
        except CompactHTTPError as exc:
            # Re-wrap to ensure any body created by injected fakes is redacted too.
            raise CompactHTTPError(exc.status, exc.body) from exc
        except Exception as exc:
            message = redact_secret(str(exc))
            if message != str(exc):
                raise RuntimeError(message) from exc
            raise

    def _api_key_request(self, *, compact: bool = True) -> tuple[str, Dict[str, str]]:
        api_key = self.config.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for codex_compact auth_mode=api_key")
        base_url = (self.config.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        endpoint = "responses/compact" if compact else "responses"
        return f"{base_url}/{endpoint}", {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _codex_oauth_request(self, *, compact: bool = True) -> tuple[str, Dict[str, str]]:
        creds = resolve_codex_credentials(self._codex_resolver)
        token = creds["api_key"]
        base_url = (creds.get("base_url") or "https://chatgpt.com/backend-api/codex").rstrip("/")
        headers = build_codex_headers(token, self._codex_header_builder)
        endpoint = "responses/compact" if compact else "responses"
        return f"{base_url}/{endpoint}", headers

    def _auto_request(self, *, compact: bool = True) -> tuple[str, Dict[str, str]]:
        if self.config.openai_api_key or os.environ.get("OPENAI_API_KEY"):
            return self._api_key_request(compact=compact)
        return self._codex_oauth_request(compact=compact)
