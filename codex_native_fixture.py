"""Codex-native fixture loading for remote compact parity smoke."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class CodexNativeFixture:
    payload: Dict[str, Any]
    identity_headers: Dict[str, str]
    metadata: Dict[str, Any]


def _string_metadata(metadata: Dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else ""


def load_codex_native_fixture(path: Path | str) -> CodexNativeFixture:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Codex-native fixture must be a JSON object")
    request = data.get("request")
    if not isinstance(request, dict):
        raise ValueError("Codex-native fixture requires object field `request`")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    payload = copy.deepcopy(request)
    headers = {
        "session_id": _string_metadata(metadata, "session_id"),
        "x-codex-window-id": _string_metadata(metadata, "window_id"),
        "x-codex-installation-id": _string_metadata(metadata, "installation_id"),
    }
    headers = {key: value for key, value in headers.items() if value}
    return CodexNativeFixture(payload=payload, identity_headers=headers, metadata=dict(metadata))
