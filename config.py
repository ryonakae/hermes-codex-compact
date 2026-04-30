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
    message_shape: str = "response_item"
    instruction_policy: str = "all_instructions"
    missing_tool_output_policy: str = "drop"
    preprocessing_mode: str = "safe_truncate"
    parallel_tool_calls: bool = False
    reasoning_effort: Optional[str] = None
    reasoning_summary: Optional[str] = None
    verbosity: Optional[str] = None
    base_instructions: str = ""
    base_instructions_file: str = ""
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
    if config.message_shape not in {"response_item", "core"}:
        raise ValueError(f"Unsupported codex_compact.message_shape: {config.message_shape}")
    if config.instruction_policy not in {"all_instructions", "codex_base_only"}:
        raise ValueError(f"Unsupported codex_compact.instruction_policy: {config.instruction_policy}")
    if config.missing_tool_output_policy not in {"drop", "keep", "aborted"}:
        raise ValueError(f"Unsupported codex_compact.missing_tool_output_policy: {config.missing_tool_output_policy}")
    if config.preprocessing_mode not in {"safe_truncate", "codex_parity"}:
        raise ValueError(f"Unsupported codex_compact.preprocessing_mode: {config.preprocessing_mode}")
    config.threshold = float(config.threshold)
    config.recent_tail_messages = int(config.recent_tail_messages)
    config.max_tool_result_chars = int(config.max_tool_result_chars)
    config.parallel_tool_calls = bool(config.parallel_tool_calls)
    config.request_timeout_seconds = int(config.request_timeout_seconds)
    if config.max_input_item_chars is not None:
        config.max_input_item_chars = int(config.max_input_item_chars)
    if config.base_instructions_file:
        instructions_path = Path(str(config.base_instructions_file)).expanduser()
        if instructions_path.exists():
            config.base_instructions = instructions_path.read_text()
    return config
