"""Plaintext Hermes JSONL compact fixture loading and safe metrics."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

try:
    from .compact_preprocess import estimate_response_item_visible_chars, response_item_type_counts
except ImportError:  # pragma: no cover - local test fallback
    from compact_preprocess import estimate_response_item_visible_chars, response_item_type_counts


@dataclass(frozen=True)
class HermesPlaintextFixture:
    payload: Dict[str, Any]
    identity_headers: Dict[str, str]
    metadata: Dict[str, Any]


def _string_metadata(metadata: Dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else ""


def _scan_forbidden(value: Any, *, path: str = "request.input") -> int:
    encrypted_fields = 0
    if isinstance(value, dict):
        if "encrypted_content" in value:
            encrypted_fields += 1
        if value.get("type") == "compaction":
            raise ValueError(f"Plaintext fixture must not include compaction items at {path}")
        for key, nested in value.items():
            encrypted_fields += _scan_forbidden(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            encrypted_fields += _scan_forbidden(nested, path=f"{path}[{index}]")
    return encrypted_fields


def safe_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    forbidden = _scan_forbidden(payload, path="request")
    if forbidden:
        raise ValueError("Plaintext fixture must not include encrypted_content")
    input_items = payload.get("input") if isinstance(payload.get("input"), list) else []
    return {
        "model": payload.get("model"),
        "input_items": len(input_items),
        "response_item_types": response_item_type_counts([item for item in input_items if isinstance(item, dict)]),
        "visible_chars": sum(
            estimate_response_item_visible_chars(item) for item in input_items if isinstance(item, dict)
        ),
        "instruction_chars": len(str(payload.get("instructions") or "")),
        "tools": len(payload.get("tools") or []),
        "parallel_tool_calls": bool(payload.get("parallel_tool_calls")),
        "forbidden_encrypted_fields": forbidden,
    }


def load_hermes_plaintext_fixture(path: Path | str) -> HermesPlaintextFixture:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Hermes plaintext fixture must be a JSON object")
    request = data.get("request")
    if not isinstance(request, dict):
        raise ValueError("Hermes plaintext fixture requires object field `request`")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    payload = copy.deepcopy(request)
    safe_metrics(payload)
    headers = {
        "session_id": _string_metadata(metadata, "session_id"),
        "x-codex-window-id": _string_metadata(metadata, "window_id"),
        "x-codex-installation-id": _string_metadata(metadata, "installation_id"),
    }
    headers = {key: value for key, value in headers.items() if value}
    return HermesPlaintextFixture(payload=payload, identity_headers=headers, metadata=dict(metadata))
