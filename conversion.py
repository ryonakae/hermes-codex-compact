"""Message conversion helpers for the hermes-codex-compact PoC."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

COMPACT_INSTRUCTION_BASE = """You are performing a CONTEXT CHECKPOINT COMPACTION for Hermes Agent.
Create a handoff summary for another LLM that will resume the task.

Include:
- Current user goal and intent
- Current progress and key decisions made
- Important constraints, preferences, and safety requirements
- Relevant files, commands, APIs, and paths
- What remains to be done as clear next steps
- Critical data, examples, errors, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
Do not invent completed work. Preserve uncertainty and blockers."""

_IMAGE_TYPES = {
    "image",
    "input_image",
    "image_url",
    "input_audio",
    "audio",
    "file",
    "attachment",
}


def truncate_text(text: str, max_chars: Optional[int]) -> str:
    """Truncate text with an explicit omission marker."""
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n[... truncated {omitted} chars ...]"


def content_to_text(content: Any) -> str:
    """Convert OpenAI/Hermes-style message content into safe readable text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        return "[binary content omitted]"
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, dict):
                part_type = str(part.get("type", "")).lower()
                if part_type in _IMAGE_TYPES or any(k in part for k in ("image_url", "input_image")):
                    parts.append(f"[{part_type or 'media'} omitted]")
                elif "text" in part:
                    parts.append(str(part.get("text") or ""))
                elif "content" in part:
                    parts.append(content_to_text(part.get("content")))
                else:
                    parts.append(json.dumps(part, ensure_ascii=False, sort_keys=True))
            else:
                parts.append(content_to_text(part))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        if "text" in content:
            return str(content.get("text") or "")
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    return str(content)


def _tool_call_name(tool_call: Dict[str, Any]) -> str:
    function = tool_call.get("function") or {}
    if isinstance(function, dict):
        return str(function.get("name") or tool_call.get("name") or tool_call.get("id") or "unknown")
    return str(tool_call.get("name") or tool_call.get("id") or "unknown")


def _format_tool_calls(tool_calls: Iterable[Dict[str, Any]]) -> str:
    lines = ["[Assistant requested tool calls]"]
    for call in tool_calls:
        function = call.get("function") or {}
        arguments = ""
        if isinstance(function, dict):
            arguments = function.get("arguments") or ""
        lines.append(f"- {call.get('id', '')} {_tool_call_name(call)} {arguments}".strip())
    return "\n".join(lines)


def hermes_message_to_responses_input_item(
    message: Dict[str, Any],
    *,
    max_content_chars: Optional[int] = None,
) -> Optional[Dict[str, str]]:
    """Flatten one Hermes/OpenAI-format message for compact input."""
    role = message.get("role")
    content = truncate_text(content_to_text(message.get("content")), max_content_chars)

    if role == "system":
        return {"role": "user", "content": f"[System context]\n{content}".strip()}
    if role == "developer":
        return {"role": "user", "content": f"[Developer context]\n{content}".strip()}
    if role == "user":
        return {"role": "user", "content": content}
    if role == "assistant":
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            tool_text = _format_tool_calls(tool_calls)
            content = f"{content}\n\n{tool_text}".strip()
        return {"role": "assistant", "content": content}
    if role == "tool":
        label = message.get("name") or "tool"
        tool_call_id = message.get("tool_call_id") or "unknown_call"
        return {"role": "user", "content": f"[Tool result: {label} / {tool_call_id}]\n{content}".strip()}
    if content:
        return {"role": "user", "content": f"[{role or 'unknown'} message]\n{content}"}
    return None


def build_compact_instructions(focus_topic: Optional[str] = None) -> str:
    instructions = COMPACT_INSTRUCTION_BASE
    if focus_topic:
        instructions = f"{instructions}\n\nFocus especially on: {focus_topic}"
    return instructions


def hermes_messages_to_compact_payload(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    focus_topic: Optional[str] = None,
    max_content_chars: Optional[int] = None,
) -> Dict[str, Any]:
    input_items = []
    for message in messages:
        item = hermes_message_to_responses_input_item(message, max_content_chars=max_content_chars)
        if item:
            input_items.append(item)
    return {
        "model": model,
        "input": input_items,
        "instructions": build_compact_instructions(focus_topic),
        "tools": [],
        "parallel_tool_calls": False,
    }


def _flatten_content_list(content: Any) -> List[str]:
    texts: List[str] = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("output_text")
                if text:
                    texts.append(str(text))
                elif part.get("content"):
                    texts.extend(_flatten_content_list(part.get("content")))
            elif isinstance(part, str):
                texts.append(part)
    elif isinstance(content, str):
        texts.append(content)
    return texts


def extract_compact_text(response: Dict[str, Any]) -> str:
    """Extract text from known OpenAI Responses compact shapes."""
    if not isinstance(response, dict):
        raise ValueError("Could not extract compact text: response is not a dict")
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts: List[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    texts.append(item["text"])
                texts.extend(_flatten_content_list(item.get("content")))
            elif isinstance(item, str):
                texts.append(item)

    if texts:
        return "\n".join(t.strip() for t in texts if t and t.strip()).strip()
    raise ValueError("Could not extract compact text from response")
