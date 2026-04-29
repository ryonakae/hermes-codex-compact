"""Configuration helpers for hermes-codex-compact."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is present in Hermes, keep fallback defensive.
    yaml = None


@dataclass
class CodexCompactConfig:
    auth_mode: str = "api_key"
    model: str = "gpt-5.1-codex"
    threshold: float = 0.85
    recent_tail_messages: int = 8
    max_tool_result_chars: int = 4000
    max_input_item_chars: Optional[int] = None
    request_timeout_seconds: int = 120
    debug_dump: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


def _load_config_file() -> Dict[str, Any]:
    path = _hermes_home() / "config.yaml"
    if not path.exists() or yaml is None:
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def load_config(overrides: Optional[Dict[str, Any]] = None) -> CodexCompactConfig:
    data = _load_config_file().get("codex_compact", {})
    if not isinstance(data, dict):
        data = {}
    merged = {**data, **(overrides or {})}
    config = CodexCompactConfig()
    for key, value in merged.items():
        if hasattr(config, key):
            setattr(config, key, value)
    if config.auth_mode not in {"api_key", "codex_oauth", "auto"}:
        raise ValueError(f"Unsupported codex_compact.auth_mode: {config.auth_mode}")
    config.threshold = float(config.threshold)
    config.recent_tail_messages = int(config.recent_tail_messages)
    config.max_tool_result_chars = int(config.max_tool_result_chars)
    config.request_timeout_seconds = int(config.request_timeout_seconds)
    if config.max_input_item_chars is not None:
        config.max_input_item_chars = int(config.max_input_item_chars)
    return config
