"""Build Codex-like compact payloads and preprocess ResponseItems."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

try:
    from .responses_conversion import hermes_messages_to_response_items, sanitize_response_tool_pairs
except ImportError:  # pragma: no cover - local test fallback
    from responses_conversion import hermes_messages_to_response_items, sanitize_response_tool_pairs


def response_item_type_counts(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        item_type = str(item.get("type") or item.get("role") or "unknown")
        counts[item_type] = counts.get(item_type, 0) + 1
    return counts


def responses_tools_from_chat_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Convert OpenAI chat-completions tool schemas to Responses function tools."""
    converted: List[Dict[str, Any]] = []
    for item in tools or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function" and isinstance(item.get("name"), str):
            parameters = item.get("parameters")
            converted.append({
                "type": "function",
                "name": item["name"].strip(),
                "description": str(item.get("description") or ""),
                "strict": bool(item.get("strict", False)),
                "parameters": parameters if isinstance(parameters, dict) else {"type": "object", "properties": {}},
            })
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        parameters = function.get("parameters")
        converted.append({
            "type": "function",
            "name": name.strip(),
            "description": str(function.get("description") or ""),
            "strict": bool(function.get("strict", False)),
            "parameters": parameters if isinstance(parameters, dict) else {"type": "object", "properties": {}},
        })
    return converted


def estimate_response_item_visible_chars(item: Dict[str, Any]) -> int:
    item_type = item.get("type")
    if item_type == "message":
        total = 0
        for part in item.get("content") or []:
            if isinstance(part, dict):
                total += len(str(part.get("text") or ""))
            elif part is not None:
                total += len(str(part))
        return total
    if item_type is None and item.get("role") in {"user", "assistant", "developer"}:
        content = item.get("content", "")
        if isinstance(content, str):
            return len(content)
        if isinstance(content, list):
            return sum(len(str(part.get("text") or part)) if isinstance(part, dict) else len(str(part)) for part in content)
        return len(str(content))
    if item_type == "function_call":
        return len(str(item.get("name") or "")) + len(str(item.get("arguments") or ""))
    if item_type == "function_call_output":
        return len(str(item.get("output") or ""))
    if item_type == "reasoning":
        return len(str(item.get("summary") or ""))
    return len(str(item))


def _visible_chars(items: List[Dict[str, Any]]) -> int:
    return sum(estimate_response_item_visible_chars(item) for item in items)


def truncate_large_function_outputs(
    items: List[Dict[str, Any]],
    *,
    max_tool_output_chars: Optional[int],
) -> Tuple[List[Dict[str, Any]], int]:
    if not max_tool_output_chars or max_tool_output_chars <= 0:
        return copy.deepcopy(items), 0
    truncated = 0
    result = copy.deepcopy(items)
    for item in result:
        if item.get("type") != "function_call_output":
            continue
        output = item.get("output")
        if output is None:
            output = ""
        elif not isinstance(output, str):
            output = str(output)
        if len(output) > max_tool_output_chars:
            omitted = len(output) - max_tool_output_chars
            item["output"] = f"{output[:max_tool_output_chars]}\n[... truncated {omitted} chars ...]"
            truncated += 1
    return result, truncated


def _latest_user_index(items: List[Dict[str, Any]]) -> Optional[int]:
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if item.get("role") == "user" and item.get("type") in {None, "message"}:
            return index
    return None


def _find_oldest_tool_pair(items: List[Dict[str, Any]], *, protect_index: Optional[int]) -> Optional[Tuple[int, int]]:
    call_positions: Dict[str, int] = {}
    for index, item in enumerate(items):
        if protect_index is not None and index >= protect_index:
            break
        if item.get("type") == "function_call" and item.get("call_id"):
            call_positions[str(item["call_id"])] = index
        elif item.get("type") == "function_call_output" and item.get("call_id"):
            call_id = str(item["call_id"])
            if call_id in call_positions:
                return call_positions[call_id], index
    return None


def trim_response_items_to_budget(
    items: List[Dict[str, Any]],
    *,
    budget_chars: Optional[int],
    preserve_latest_user: bool = True,
) -> Tuple[List[Dict[str, Any]], int]:
    if not budget_chars or budget_chars <= 0:
        return copy.deepcopy(items), 0
    result = copy.deepcopy(items)
    removed_pairs = 0
    while _visible_chars(result) > budget_chars:
        protect_index = _latest_user_index(result) if preserve_latest_user else None
        pair = _find_oldest_tool_pair(result, protect_index=protect_index)
        if pair is None:
            break
        start, end = pair
        del result[end]
        del result[start]
        removed_pairs += 1
    return sanitize_response_tool_pairs(result, drop_incomplete_tool_pairs=True), removed_pairs


def build_codex_compact_payload(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    parallel_tool_calls: bool = False,
    reasoning: Optional[Dict[str, Any]] = None,
    text: Optional[Dict[str, Any]] = None,
    max_tool_output_chars: Optional[int] = None,
    token_budget_chars: Optional[int] = None,
    message_shape: str = "response_item",
    instruction_policy: str = "all_instructions",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    items, instructions = hermes_messages_to_response_items(
        messages,
        drop_incomplete_tool_pairs=False,
        message_shape=message_shape,
        instruction_policy=instruction_policy,
    )
    items, truncated_outputs = truncate_large_function_outputs(
        items,
        max_tool_output_chars=max_tool_output_chars,
    )
    items, removed_pairs = trim_response_items_to_budget(
        items,
        budget_chars=token_budget_chars,
        preserve_latest_user=True,
    )
    items = sanitize_response_tool_pairs(items, drop_incomplete_tool_pairs=True)

    responses_tools = responses_tools_from_chat_tools(tools)
    payload: Dict[str, Any] = {
        "model": model,
        "input": items,
        "instructions": instructions,
        "tools": responses_tools,
        "parallel_tool_calls": bool(parallel_tool_calls),
    }
    if reasoning is not None:
        payload["reasoning"] = reasoning
    if text is not None:
        payload["text"] = text

    stats = {
        "original_messages": len(messages or []),
        "input_items": len(items),
        "response_item_types": response_item_type_counts(items),
        "visible_chars": _visible_chars(items),
        "instruction_chars": len(instructions),
        "tools": len(payload["tools"]),
        "truncated_tool_outputs": truncated_outputs,
        "removed_tool_pairs": removed_pairs,
    }
    return payload, stats
