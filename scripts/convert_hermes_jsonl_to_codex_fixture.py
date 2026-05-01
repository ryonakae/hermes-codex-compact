#!/usr/bin/env python3
"""Convert Hermes JSONL session exports into plaintext Codex compact fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compact_preprocess import build_codex_compact_payload  # noqa: E402
from hermes_plaintext_fixture import safe_metrics  # noqa: E402
from session_fixtures import load_session_messages, summarize_messages  # noqa: E402
from tool_schemas import extract_tool_names_from_messages, minimal_fixture_tool_schemas  # noqa: E402

RECENT_TAIL_PRIORITY = (
    "Recent Tail Priority: Preserve the latest explicit user direction, implementation state, "
    "pushed commits, failing tests, and next action. If older plans conflict with recent user "
    "instructions, follow the recent user instructions."
)

BASE_INSTRUCTIONS = (
    "You are compacting a plaintext Hermes Agent session export for future continuation. "
    "Preserve the user's goal, decisions, completed work, relevant files, commands, constraints, "
    "blockers, and next steps. Do not copy raw tool output unless it is necessary to resume."
)


def _normalize_focus_topic(focus_topic: str | None) -> str:
    topic = " ".join(str(focus_topic or "").split())[:500]
    return topic


def _append_instructions(payload: Dict[str, Any], *, focus_topic: str | None, recent_tail_messages: int) -> Dict[str, Any]:
    instructions = str(payload.get("instructions") or "").strip()
    sections = [instructions] if instructions else []
    if BASE_INSTRUCTIONS and BASE_INSTRUCTIONS not in sections:
        sections.append(BASE_INSTRUCTIONS)
    topic = _normalize_focus_topic(focus_topic)
    if topic:
        sections.append(f"Compaction focus: prioritize preserving context needed to continue this task: {topic}")
    if recent_tail_messages > 0:
        sections.append(f"{RECENT_TAIL_PRIORITY} Treat the last {recent_tail_messages} messages as highest priority.")
    payload = dict(payload)
    payload["instructions"] = "\n\n".join(sections)
    return payload


def _is_private_fixture_output(path: Path) -> bool:
    parts = path.expanduser().resolve().parts
    for index in range(len(parts) - 2):
        if parts[index:index + 3] == ("tests", "fixtures", "private"):
            return True
    return False


def build_fixture_document(
    source: Path | str,
    *,
    model: str,
    focus_topic: str = "",
    max_tool_output_chars: int = 4000,
    recent_tail_messages: int = 12,
    max_input_item_chars: int | None = None,
) -> Dict[str, Any]:
    source_path = Path(source).expanduser()
    messages = load_session_messages(source_path)
    tools = minimal_fixture_tool_schemas(extract_tool_names_from_messages(messages))
    payload, stats = build_codex_compact_payload(
        messages,
        model=model,
        tools=tools,
        parallel_tool_calls=True,
        reasoning={"effort": "medium", "summary": "auto"},
        text=None,
        max_tool_output_chars=max_tool_output_chars,
        token_budget_chars=max_input_item_chars,
        message_shape="response_item",
        instruction_policy="all_instructions",
        missing_tool_output_policy="drop",
        base_instructions=BASE_INSTRUCTIONS,
    )
    payload["text"] = None
    payload = _append_instructions(payload, focus_topic=focus_topic, recent_tail_messages=recent_tail_messages)
    metrics = safe_metrics(payload)
    return {
        "metadata": {
            "source": "hermes-jsonl-plaintext",
            "source_file": source_path.name,
            "model": model,
            "focus_topic": _normalize_focus_topic(focus_topic),
            "encrypted_content": False,
            "message_summary": summarize_messages(messages),
            "stats": {**stats, "safe_metrics": metrics},
            "warnings": [],
        },
        "request": payload,
    }


def _default_output_path(source: Path) -> Path:
    return Path("tests/fixtures/private") / f"{source.stem}.hermes-plaintext.compact.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Hermes session JSONL export")
    parser.add_argument("--output", default="", help="Output fixture JSON path; defaults under tests/fixtures/private/")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--focus-topic", default="")
    parser.add_argument("--max-tool-output-chars", type=int, default=4000)
    parser.add_argument("--recent-tail-messages", type=int, default=12)
    parser.add_argument("--max-input-item-chars", type=int, default=0)
    parser.add_argument("--allow-public-output", action="store_true", help="Allow writing outside tests/fixtures/private/")
    args = parser.parse_args(argv)

    source = Path(args.input).expanduser()
    output = Path(args.output).expanduser() if args.output else _default_output_path(source)
    if not args.allow_public_output and not _is_private_fixture_output(output):
        parser.error("Refusing to write plaintext session fixture outside tests/fixtures/private/ without --allow-public-output")

    document = build_fixture_document(
        source,
        model=args.model,
        focus_topic=args.focus_topic,
        max_tool_output_chars=args.max_tool_output_chars,
        recent_tail_messages=args.recent_tail_messages,
        max_input_item_chars=args.max_input_item_chars or None,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metrics = safe_metrics(document["request"])
    print(json.dumps({"output": str(output), "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
