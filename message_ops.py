"""Message preparation and replacement-history helpers."""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Set

try:
    from .conversion import truncate_text
except ImportError:  # pragma: no cover - local test fallback
    from conversion import truncate_text

CHECKPOINT_MESSAGE_PREFIX = """[Context compacted by hermes-codex-compact]

The following is a compacted checkpoint of prior conversation and tool work.
Treat it as historical context, not as a new user request.
Continue from the current user request using this context.

<checkpoint>
"""
CHECKPOINT_MESSAGE_SUFFIX = "\n</checkpoint>"


def prepare_for_compact(
    messages: List[Dict[str, Any]],
    *,
    max_tool_result_chars: int = 4000,
) -> List[Dict[str, Any]]:
    """Return a copy with oversized tool results shortened."""
    prepared = copy.deepcopy(messages)
    for message in prepared:
        if message.get("role") == "tool" and isinstance(message.get("content"), str):
            message["content"] = truncate_text(message["content"], max_tool_result_chars)
    return prepared


def _tool_call_ids(message: Dict[str, Any]) -> Set[str]:
    ids: Set[str] = set()
    for call in message.get("tool_calls") or []:
        call_id = call.get("id")
        if call_id:
            ids.add(str(call_id))
    return ids


def sanitize_tail_tool_pairs(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop dangling assistant tool calls and orphan tool results.

    This is intentionally conservative for the PoC: complete assistant tool_call
    + tool result pairs are kept; incomplete pairs are removed instead of stubbed.
    """
    produced_ids: Set[str] = set()
    result_ids: Set[str] = set()
    for message in messages:
        produced_ids.update(_tool_call_ids(message))
        if message.get("role") == "tool" and message.get("tool_call_id"):
            result_ids.add(str(message["tool_call_id"]))

    keep_ids = produced_ids & result_ids
    sanitized: List[Dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "tool":
            if str(message.get("tool_call_id") or "") in keep_ids:
                sanitized.append(message)
            continue
        ids = _tool_call_ids(message)
        if ids and not ids.issubset(keep_ids):
            # Dropping the entire assistant message is safer than returning a
            # tool_call without its required tool result.
            continue
        sanitized.append(message)
    return sanitized


def _system_messages(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [copy.deepcopy(m) for m in messages if m.get("role") in {"system", "developer"}]


def _recent_tail(messages: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    if count <= 0:
        return []
    non_system = [copy.deepcopy(m) for m in messages if m.get("role") not in {"system", "developer"}]
    return non_system[-count:]


def checkpoint_message(compact_text: str) -> Dict[str, str]:
    return {
        "role": "user",
        "content": f"{CHECKPOINT_MESSAGE_PREFIX}{compact_text.strip()}{CHECKPOINT_MESSAGE_SUFFIX}",
    }


def build_replacement_history(
    original_messages: List[Dict[str, Any]],
    compact_text: str,
    *,
    recent_tail_messages: int = 8,
) -> List[Dict[str, Any]]:
    replacement = _system_messages(original_messages)
    replacement.append(checkpoint_message(compact_text))
    replacement.extend(_recent_tail(original_messages, recent_tail_messages))
    return sanitize_tail_tool_pairs(replacement)
