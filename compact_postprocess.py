"""Post-process compact endpoint responses into Hermes chat messages."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from .conversion import extract_compact_text
    from .message_ops import build_replacement_history, sanitize_tail_tool_pairs
except ImportError:  # pragma: no cover - local test fallback
    from conversion import extract_compact_text
    from message_ops import build_replacement_history, sanitize_tail_tool_pairs


def _content_parts_to_text(content: Any) -> str:
    texts: List[str] = []
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, str):
                if part:
                    texts.append(part)
                continue
            if not isinstance(part, dict):
                if part is not None:
                    texts.append(str(part))
                continue
            text = part.get("text") or part.get("output_text")
            if text is not None:
                texts.append(str(text))
            elif part.get("content") is not None:
                nested = _content_parts_to_text(part.get("content"))
                if nested:
                    texts.append(nested)
    elif isinstance(content, dict):
        if content.get("text") is not None:
            return str(content.get("text"))
        if content.get("content") is not None:
            return _content_parts_to_text(content.get("content"))
    elif content is not None:
        return str(content)
    return "\n".join(texts).strip()


def should_keep_compacted_response_item(item: Dict[str, Any]) -> bool:
    item_type = item.get("type")
    if item_type == "message":
        role = item.get("role")
        if role == "developer":
            return False
        return role in {"user", "assistant"}
    if item_type == "compaction":
        return True
    return False


def response_item_to_hermes_message(item: Dict[str, Any]) -> Optional[Dict[str, str]]:
    item_type = item.get("type")
    if item_type == "message":
        role = item.get("role")
        if role not in {"user", "assistant", "system", "developer"}:
            return None
        text = _content_parts_to_text(item.get("content"))
        return {"role": str(role), "content": text}
    if item_type == "compaction":
        text = _content_parts_to_text(item.get("summary") or item.get("content") or item.get("text"))
        if text:
            return {"role": "user", "content": text}
    return None


def _structured_output_messages(response: Dict[str, Any]) -> List[Dict[str, str]]:
    output = response.get("output")
    if not isinstance(output, list):
        return []
    messages: List[Dict[str, str]] = []
    fallback_texts: List[str] = []
    for item in output:
        if isinstance(item, dict) and should_keep_compacted_response_item(item):
            message = response_item_to_hermes_message(item)
            if message is not None:
                messages.append(message)
        elif isinstance(item, dict):
            text = _content_parts_to_text(item.get("content"))
            if text:
                fallback_texts.append(text)
        elif isinstance(item, str):
            fallback_texts.append(item)
    if messages:
        return messages
    if fallback_texts:
        return build_replacement_history([], "\n".join(fallback_texts), recent_tail_messages=0)
    return []


def compact_response_to_hermes_messages(
    response: Dict[str, Any],
    original_messages: List[Dict[str, Any]],
    *,
    recent_tail_messages: int = 0,
) -> List[Dict[str, Any]]:
    """Convert compact endpoint response into valid Hermes chat messages."""
    messages = _structured_output_messages(response)
    if not messages:
        compact_text = extract_compact_text(response)
        messages = build_replacement_history([], compact_text, recent_tail_messages=0)

    if recent_tail_messages > 0:
        tail = [m.copy() for m in (original_messages or []) if m.get("role") not in {"system", "developer"}]
        messages.extend(tail[-recent_tail_messages:])

    return sanitize_tail_tool_pairs(messages)
