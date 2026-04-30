"""Convert Hermes chat-format messages to Codex/OpenAI Responses items.

This module intentionally mirrors the subset of Hermes' internal
`agent.codex_responses_adapter._chat_messages_to_responses_input()` that is
needed for compact payload construction, while staying standalone-plugin safe.
"""

from __future__ import annotations
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

MESSAGE_ROLES_WITH_INSTRUCTIONS = {"system", "developer"}
_TEXT_TYPES = {"text", "input_text", "output_text"}
_MEDIA_TYPES = {"image", "input_image", "image_url", "input_audio", "audio", "file", "attachment"}
_RESPONSE_MESSAGE_STATUSES = {"completed", "incomplete", "in_progress"}
_MESSAGE_SHAPES = {"response_item", "core"}
_INSTRUCTION_POLICIES = {"all_instructions", "codex_base_only"}


def deterministic_call_id(name: str, arguments: str, index: int = 0) -> str:
    """Return a stable Responses-style function call id."""
    seed = f"{name}:{arguments}:{index}"
    digest = hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"call_{digest}"


def split_responses_tool_id(raw_id: Any) -> Tuple[Optional[str], Optional[str]]:
    """Split Hermes-stored Responses tool id into (call_id, response_item_id).

    Hermes core stores some Codex tool IDs as `call_id|fc_id`. If only an
    `fc_...` response item id is present, callers can derive `call_...` from it.
    """
    if not isinstance(raw_id, str):
        return None, None
    value = raw_id.strip()
    if not value:
        return None, None
    if "|" in value:
        call_id, response_item_id = value.split("|", 1)
        return call_id.strip() or None, response_item_id.strip() or None
    if value.startswith("fc_"):
        return None, value
    return value, None


def call_id_from_response_item_id(response_item_id: Optional[str]) -> Optional[str]:
    if isinstance(response_item_id, str) and response_item_id.startswith("fc_"):
        suffix = response_item_id[len("fc_"):]
        if suffix:
            return f"call_{suffix}"
    return None


def _normalize_responses_message_status(value: Any, *, default: str = "completed") -> str:
    if isinstance(value, str):
        status = value.strip().lower().replace("-", "_").replace(" ", "_")
        if status in _RESPONSE_MESSAGE_STATUSES:
            return status
    return default


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _instruction_text(content: Any) -> str:
    parts = content_to_response_content_parts(content, role="user")
    return "\n".join(part.get("text", "") for part in parts if part.get("text"))


def content_to_response_content_parts(content: Any, *, role: str) -> List[Dict[str, str]]:
    """Convert Hermes/OpenAI chat content into Responses content parts."""
    text_type = "output_text" if role == "assistant" else "input_text"
    if content is None:
        return []
    if isinstance(content, bytes):
        return [{"type": text_type, "text": "[binary content omitted]"}]
    if isinstance(content, str):
        return [{"type": text_type, "text": content}] if content else []
    if isinstance(content, list):
        converted: List[Dict[str, str]] = []
        for part in content:
            if isinstance(part, str):
                if part:
                    converted.append({"type": text_type, "text": part})
                continue
            if not isinstance(part, dict):
                text = _json_text(part)
                if text:
                    converted.append({"type": text_type, "text": text})
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type in _TEXT_TYPES:
                text = part.get("text")
                if text is None:
                    text = part.get("content")
                text = _json_text(text)
                if text:
                    converted.append({"type": text_type, "text": text})
                continue
            if part_type in _MEDIA_TYPES or any(key in part for key in ("image_url", "input_image")):
                converted.append({"type": text_type, "text": f"[{part_type or 'media'} omitted]"})
                continue
            if "content" in part:
                converted.extend(content_to_response_content_parts(part.get("content"), role=role))
                continue
            text = _json_text(part)
            if text:
                converted.append({"type": text_type, "text": text})
        return converted
    if isinstance(content, dict):
        if "text" in content:
            text = _json_text(content.get("text"))
        elif "content" in content:
            return content_to_response_content_parts(content.get("content"), role=role)
        else:
            text = _json_text(content)
        return [{"type": text_type, "text": text}] if text else []
    text = str(content)
    return [{"type": text_type, "text": text}] if text else []


def _core_content(content: Any, *, role: str) -> Any:
    if isinstance(content, str) or content is None:
        return content or ""
    return content_to_response_content_parts(content, role=role)


def _message_item(role: str, content: Any, *, message_shape: str) -> Optional[Dict[str, Any]]:
    if message_shape == "core" and isinstance(content, str):
        if not content:
            return None
        return {"role": role, "content": content}
    parts = content_to_response_content_parts(content, role=role)
    if not parts:
        return None
    if message_shape == "core":
        return {"role": role, "content": parts}
    return {"type": "message", "role": role, "content": parts}


def _tool_call_parts(tool_call: Dict[str, Any], index: int) -> Optional[Dict[str, str]]:
    function = tool_call.get("function") or {}
    if not isinstance(function, dict):
        function = {}
    name = function.get("name") or tool_call.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    arguments = function.get("arguments", tool_call.get("arguments", "{}"))
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments, ensure_ascii=False)
    elif not isinstance(arguments, str):
        arguments = str(arguments)
    arguments = arguments.strip() or "{}"

    embedded_call_id, embedded_response_item_id = split_responses_tool_id(tool_call.get("id"))
    call_id = tool_call.get("call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        call_id = embedded_call_id or call_id_from_response_item_id(embedded_response_item_id)
    if not isinstance(call_id, str) or not call_id.strip():
        call_id = deterministic_call_id(name, arguments, index)

    return {
        "type": "function_call",
        "call_id": call_id.strip(),
        "name": name,
        "arguments": arguments,
    }


def _reasoning_items(message: Dict[str, Any], seen_reasoning_ids: set) -> List[Dict[str, Any]]:
    replay: List[Dict[str, Any]] = []
    raw_items = message.get("codex_reasoning_items")
    if not isinstance(raw_items, list):
        return replay
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        encrypted = item.get("encrypted_content")
        if not isinstance(encrypted, str) or not encrypted:
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            if item_id in seen_reasoning_ids:
                continue
            seen_reasoning_ids.add(item_id)
        reasoning = {k: v for k, v in item.items() if k != "id"}
        reasoning["type"] = "reasoning"
        reasoning["encrypted_content"] = encrypted
        if not isinstance(reasoning.get("summary"), list):
            reasoning["summary"] = []
        replay.append(reasoning)
    return replay


def replay_codex_message_items(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Replay stored assistant Responses message items exactly where safe."""
    raw_items = message.get("codex_message_items")
    if not isinstance(raw_items, list):
        return []
    replayed: List[Dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        if raw.get("type") != "message" or raw.get("role") != "assistant":
            continue
        raw_content = raw.get("content")
        if not isinstance(raw_content, list):
            continue
        content: List[Dict[str, str]] = []
        for part in raw_content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").strip()
            if part_type not in {"text", "output_text"}:
                continue
            text = part.get("text", "")
            if text is None:
                text = ""
            elif not isinstance(text, str):
                text = str(text)
            content.append({"type": "output_text", "text": text})
        if not content:
            continue
        item: Dict[str, Any] = {
            "type": "message",
            "role": "assistant",
            "status": _normalize_responses_message_status(raw.get("status")),
            "content": content,
        }
        item_id = raw.get("id")
        if isinstance(item_id, str) and item_id.strip():
            item["id"] = item_id.strip()
        phase = raw.get("phase")
        if isinstance(phase, str) and phase.strip():
            item["phase"] = phase.strip()
        replayed.append(item)
    return replayed


def sanitize_response_tool_pairs(
    items: List[Dict[str, Any]],
    *,
    drop_incomplete_tool_pairs: bool = True,
) -> List[Dict[str, Any]]:
    """Remove orphan function outputs and optionally dangling calls."""
    call_ids = {str(item.get("call_id")) for item in items if item.get("type") == "function_call" and item.get("call_id")}
    output_ids = {str(item.get("call_id")) for item in items if item.get("type") == "function_call_output" and item.get("call_id")}
    keep_call_ids = call_ids & output_ids if drop_incomplete_tool_pairs else call_ids

    sanitized: List[Dict[str, Any]] = []
    for item in items:
        item_type = item.get("type")
        if item_type == "function_call":
            if str(item.get("call_id")) in keep_call_ids:
                sanitized.append(item)
            continue
        if item_type == "function_call_output":
            if str(item.get("call_id")) in keep_call_ids:
                sanitized.append(item)
            continue
        sanitized.append(item)
    return sanitized


def hermes_messages_to_response_items(
    messages: List[Dict[str, Any]],
    *,
    drop_incomplete_tool_pairs: bool = True,
    max_tool_output_chars: Optional[int] = None,
    message_shape: str = "response_item",
    instruction_policy: str = "all_instructions",
) -> Tuple[List[Dict[str, Any]], str]:
    """Convert Hermes chat messages to Codex-like Responses input items.

    Returns `(items, instructions)`, where system/developer messages are joined
    into `instructions` and are not emitted as input items.
    """
    if message_shape not in _MESSAGE_SHAPES:
        raise ValueError(f"Unsupported message_shape: {message_shape}")
    if instruction_policy not in _INSTRUCTION_POLICIES:
        raise ValueError(f"Unsupported instruction_policy: {instruction_policy}")

    items: List[Dict[str, Any]] = []
    instructions: List[str] = []
    tool_call_index = 0
    seen_reasoning_ids: set = set()

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role in MESSAGE_ROLES_WITH_INSTRUCTIONS:
            text = _instruction_text(message.get("content"))
            if text and not (instruction_policy == "codex_base_only" and role == "developer"):
                label = "Developer context" if role == "developer" else ""
                instructions.append(f"[{label}]\n{text}" if label else text)
            elif text:
                if message_shape == "core":
                    items.append({"role": str(role), "content": text})
                else:
                    items.append({"type": "message", "role": str(role), "content": [{"type": "input_text", "text": text}]})
            continue

        if role in {"user", "assistant"}:
            replayed_reasoning: List[Dict[str, Any]] = []
            if role == "assistant":
                replayed_reasoning = _reasoning_items(message, seen_reasoning_ids)
                items.extend(replayed_reasoning)

            replayed_messages = replay_codex_message_items(message) if role == "assistant" else []
            if replayed_messages:
                items.extend(replayed_messages)
            else:
                msg_item = _message_item(str(role), message.get("content"), message_shape=message_shape)
                if msg_item:
                    items.append(msg_item)
                elif role == "assistant" and replayed_reasoning and not (message.get("tool_calls") or []):
                    if message_shape == "core":
                        items.append({"role": "assistant", "content": ""})
                    else:
                        items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": ""}]})

            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                call_item = _tool_call_parts(tool_call, tool_call_index)
                tool_call_index += 1
                if call_item:
                    items.append(call_item)
            continue

        if role == "tool":
            call_id, _response_item_id = split_responses_tool_id(message.get("tool_call_id"))
            if not isinstance(call_id, str) or not call_id.strip():
                continue
            output = message.get("content", "")
            if output is None:
                output = ""
            elif not isinstance(output, str):
                output = _json_text(output)
            if max_tool_output_chars and max_tool_output_chars > 0 and len(output) > max_tool_output_chars:
                omitted = len(output) - max_tool_output_chars
                output = f"{output[:max_tool_output_chars]}\n[... truncated {omitted} chars ...]"
            items.append({"type": "function_call_output", "call_id": call_id.strip(), "output": output})

    return sanitize_response_tool_pairs(items, drop_incomplete_tool_pairs=drop_incomplete_tool_pairs), "\n\n".join(instructions)
