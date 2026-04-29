#!/usr/bin/env python3
"""Smoke test OpenAI/Codex responses/compact with a tiny or private fixture.

Default is dry-run to avoid accidental network/API usage:

    python scripts/smoke_compact.py --fixture tests/fixtures/private/real.jsonl
    python scripts/smoke_compact.py --auth-mode codex_oauth --fixture tests/fixtures/private/real.jsonl --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client import CompactClient  # noqa: E402
from config import CodexCompactConfig  # noqa: E402
from conversion import extract_compact_text, hermes_messages_to_compact_payload  # noqa: E402
from message_ops import build_replacement_history, prepare_for_compact  # noqa: E402
from session_fixtures import load_session_messages, summarize_messages  # noqa: E402

FIXTURE_MESSAGES = [
    {"role": "system", "content": "You are Hermes, a helpful coding agent."},
    {"role": "user", "content": "Build a tiny Hermes ContextEngine plugin."},
    {"role": "assistant", "content": "I created a plan and started implementing conversion helpers."},
    {"role": "tool", "tool_call_id": "call_1", "name": "pytest", "content": "25 tests passed"},
]


def build_payload(model: str, focus_topic: str | None = None) -> dict:
    return hermes_messages_to_compact_payload(
        prepare_for_compact(FIXTURE_MESSAGES),
        model=model,
        focus_topic=focus_topic,
    )


def build_payload_from_fixture(
    fixture: str | Path,
    *,
    model: str,
    focus_topic: str | None = None,
    max_tool_result_chars: int = 4000,
    max_input_item_chars: int | None = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    messages = load_session_messages(fixture)
    payload = hermes_messages_to_compact_payload(
        prepare_for_compact(messages, max_tool_result_chars=max_tool_result_chars),
        model=model,
        focus_topic=focus_topic,
        max_content_chars=max_input_item_chars,
    )
    return payload, messages


def _preview_replacement(messages: List[Dict[str, Any]], recent_tail_messages: int = 2) -> List[Dict[str, Any]]:
    return build_replacement_history(
        messages,
        "DRY RUN: compact text will be returned by the remote compact endpoint.",
        recent_tail_messages=recent_tail_messages,
    )


def compare_builtin_status(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return lightweight built-in compressor comparability info.

    Dry-run should not call auxiliary models. This reports whether Hermes' built-in
    compressor is importable and whether the fixture is large enough to attempt a
    later manual A/B run.
    """
    try:
        hermes_repo = Path.home() / ".hermes" / "hermes-agent"
        if hermes_repo.exists() and str(hermes_repo) not in sys.path:
            sys.path.insert(0, str(hermes_repo))
        from agent.context_compressor import ContextCompressor  # type: ignore

        compressor = ContextCompressor(model="gpt-5.1-codex", quiet_mode=True)
        can_compress = compressor.has_content_to_compress(messages)
        return {
            "available": True,
            "can_compress_fixture": bool(can_compress),
            "note": "Dry-run did not call built-in compressor; run a dedicated A/B smoke when ready.",
        }
    except Exception as exc:  # pragma: no cover - depends on local Hermes checkout/imports.
        return {"available": False, "reason": str(exc)}


def dry_run_summary(
    payload: Dict[str, Any],
    messages: List[Dict[str, Any]],
    *,
    fixture: str | Path | None = None,
    compare_builtin: bool = False,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "dry_run": True,
        "fixture": str(fixture) if fixture else None,
        "message_summary": summarize_messages(messages),
        "payload_summary": {
            "model": payload.get("model"),
            "input_items": len(payload.get("input") or []),
            "instruction_chars": len(payload.get("instructions") or ""),
        },
        "replacement_preview": _preview_replacement(messages),
    }
    if compare_builtin:
        result["builtin_compare"] = compare_builtin_status(messages)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-mode", choices=["api_key", "codex_oauth", "auto"], default="api_key")
    parser.add_argument("--model", default="gpt-5.1-codex")
    parser.add_argument("--focus-topic", default="")
    parser.add_argument("--fixture", default="", help="Optional JSONL fixture exported from a Hermes session")
    parser.add_argument("--recent-tail-messages", type=int, default=2)
    parser.add_argument("--max-tool-result-chars", type=int, default=4000)
    parser.add_argument("--max-input-item-chars", type=int, default=0)
    parser.add_argument("--compare-builtin", action="store_true", help="Report built-in compressor comparability without changing runtime config")
    parser.add_argument("--execute", action="store_true", help="Actually call the remote compact endpoint")
    args = parser.parse_args(argv)

    if args.fixture:
        payload, messages = build_payload_from_fixture(
            args.fixture,
            model=args.model,
            focus_topic=args.focus_topic or None,
            max_tool_result_chars=args.max_tool_result_chars,
            max_input_item_chars=args.max_input_item_chars or None,
        )
    else:
        messages = FIXTURE_MESSAGES
        payload = build_payload(args.model, args.focus_topic or None)

    if not args.execute:
        print(json.dumps(
            dry_run_summary(payload, messages, fixture=args.fixture or None, compare_builtin=args.compare_builtin),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    config = CodexCompactConfig(auth_mode=args.auth_mode, model=args.model)
    response = CompactClient(config).compact(payload)
    compact_text = extract_compact_text(response)
    replacement = build_replacement_history(
        messages,
        compact_text,
        recent_tail_messages=args.recent_tail_messages,
    )
    print(json.dumps({
        "fixture": args.fixture or None,
        "message_summary": summarize_messages(messages),
        "compact_text": compact_text,
        "replacement": replacement,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
