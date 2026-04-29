"""Load gitignored Hermes session fixtures for compact experiments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

MESSAGE_ROLES = {"system", "developer", "user", "assistant", "tool"}


def _is_message(value: Any) -> bool:
    return isinstance(value, dict) and value.get("role") in MESSAGE_ROLES


def _coerce_message(value: Dict[str, Any]) -> Dict[str, Any]:
    allowed_extra = {
        "name",
        "tool_call_id",
        "tool_calls",
        "function_call",
        "reasoning",
        "metadata",
    }
    message: Dict[str, Any] = {
        "role": value["role"],
        "content": value.get("content", ""),
    }
    for key in allowed_extra:
        if key in value:
            message[key] = value[key]
    return message


def _messages_from_row(row: Any) -> Iterable[Dict[str, Any]]:
    """Yield messages from common Hermes export / fixture JSONL row shapes."""
    if _is_message(row):
        yield _coerce_message(row)
        return
    if not isinstance(row, dict):
        return

    for key in ("message", "request", "response"):
        nested = row.get(key)
        if _is_message(nested):
            yield _coerce_message(nested)

    for key in ("messages", "conversation_history", "history"):
        nested_messages = row.get(key)
        if isinstance(nested_messages, list):
            for nested in nested_messages:
                if _is_message(nested):
                    yield _coerce_message(nested)

    # Some session stores wrap messages as event payloads.
    payload = row.get("payload") or row.get("data")
    if isinstance(payload, dict):
        yield from _messages_from_row(payload)


def load_session_messages(path: str | Path) -> List[Dict[str, Any]]:
    """Load Hermes/OpenAI-format messages from a JSONL fixture.

    Supported rows:
    - direct message objects: {"role": "user", "content": "..."}
    - wrapped rows: {"message": {...}}
    - batch rows: {"messages": [{...}, ...]}
    - shallow event wrappers: {"payload": {"message": {...}}}
    """
    fixture = Path(path).expanduser()
    messages: List[Dict[str, Any]] = []
    with fixture.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {fixture}:{line_number}: {exc}") from exc
            messages.extend(_messages_from_row(row))
    if not messages:
        raise ValueError(f"No Hermes/OpenAI messages found in fixture: {fixture}")
    return messages


def summarize_messages(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_role: Dict[str, int] = {}
    total_content_chars = 0
    tool_calls = 0
    tool_results = 0
    for message in messages:
        role = str(message.get("role") or "unknown")
        by_role[role] = by_role.get(role, 0) + 1
        content = message.get("content")
        if isinstance(content, str):
            total_content_chars += len(content)
        else:
            total_content_chars += len(json.dumps(content, ensure_ascii=False, default=str))
        tool_calls += len(message.get("tool_calls") or [])
        if role == "tool":
            tool_results += 1
    return {
        "messages": len(messages),
        "by_role": by_role,
        "content_chars": total_content_chars,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
    }
