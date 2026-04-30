"""Minimal tool schemas for compact fixture smoke tests."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


_MINIMAL_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "skill_view": {
        "description": "Load a Hermes skill or a linked skill file for task-specific guidance.",
        "properties": {
            "name": {"type": "string"},
            "file_path": {"type": "string"},
        },
    },
    "terminal": {
        "description": "Execute a shell command in the local environment and return its output.",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer"},
            "workdir": {"type": "string"},
        },
    },
    "read_file": {
        "description": "Read a text file with optional line offset and limit.",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        },
    },
    "search_files": {
        "description": "Search file names or file contents using ripgrep-style patterns.",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "target": {"type": "string"},
        },
    },
    "patch": {
        "description": "Apply targeted file edits or multi-file patches.",
        "properties": {
            "mode": {"type": "string"},
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "patch": {"type": "string"},
        },
    },
    "write_file": {
        "description": "Write complete content to a file, replacing any existing content.",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
    },
    "todo": {
        "description": "Manage the current session task list.",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
            "merge": {"type": "boolean"},
        },
    },
}


def extract_tool_names_from_messages(messages: Iterable[Dict[str, Any]]) -> List[str]:
    """Return assistant tool-call names in first-seen order."""
    names: List[str] = []
    seen = set()
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            name = None
            if isinstance(function, dict):
                name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                name = tool_call.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def minimal_fixture_tool_schemas(tool_names: Iterable[str]) -> List[Dict[str, Any]]:
    """Build minimal Responses-compatible tool schemas for known fixture tools."""
    tools: List[Dict[str, Any]] = []
    seen = set()
    for raw_name in tool_names or []:
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        if not name or name in seen or name not in _MINIMAL_TOOL_SCHEMAS:
            continue
        seen.add(name)
        spec = _MINIMAL_TOOL_SCHEMAS[name]
        tools.append({
            "type": "function",
            "name": name,
            "description": spec["description"],
            "strict": False,
            "parameters": {
                "type": "object",
                "properties": dict(spec["properties"]),
                "additionalProperties": True,
            },
        })
    return tools
