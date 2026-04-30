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
from compact_postprocess import compact_response_to_hermes_messages  # noqa: E402
from compact_preprocess import build_codex_compact_payload, response_item_type_counts  # noqa: E402
from config import CodexCompactConfig  # noqa: E402
from message_ops import build_replacement_history  # noqa: E402
from session_fixtures import load_session_messages, summarize_messages  # noqa: E402

VARIANTS = {"current", "conversion-parity", "payload-parity", "preprocessing-parity", "instructed-remote"}

HERMES_COMPACT_BASE_INSTRUCTIONS = """You are Hermes Agent, a coding and task-execution agent. You are compacting a prior agent session for future continuation. The input contains user requests, assistant progress, and structured tool calls/results. Preserve the user's goal, decisions, completed work, relevant files, commands, constraints, blockers, and next steps. Do not copy raw tool output unless it is necessary to resume."""

FIXTURE_MESSAGES = [
    {"role": "system", "content": "You are Hermes, a helpful coding agent."},
    {"role": "user", "content": "Build a tiny Hermes ContextEngine plugin."},
    {"role": "assistant", "content": "I created a plan and started implementing conversion helpers."},
    {"role": "tool", "tool_call_id": "call_1", "name": "pytest", "content": "25 tests passed"},
]


def variant_overrides(variant: str) -> Dict[str, Any]:
    if variant not in VARIANTS:
        raise ValueError(f"Unsupported smoke variant: {variant}")
    overrides: Dict[str, Any] = {}
    if variant in {"conversion-parity", "payload-parity", "preprocessing-parity", "instructed-remote"}:
        overrides["message_shape"] = "core"
    if variant in {"payload-parity", "preprocessing-parity", "instructed-remote"}:
        overrides["instruction_policy"] = "codex_base_only"
        overrides["parallel_tool_calls"] = True
    if variant == "instructed-remote":
        overrides["base_instructions"] = HERMES_COMPACT_BASE_INSTRUCTIONS
    if variant == "preprocessing-parity":
        overrides["missing_tool_output_policy"] = "aborted"
        overrides["preprocessing_mode"] = "codex_parity"
        overrides["recent_tail_messages"] = 0
    return overrides


def evaluate_handoff_quality(text: str) -> Dict[str, bool]:
    text = text or ""
    lower = text.lower()
    has_active_task = "active task" in lower or "## active" in lower
    has_completed_actions = "completed actions" in lower or "completed" in lower
    has_remaining_work = "remaining work" in lower or "next steps" in lower or "todo" in lower
    has_relevant_files = "relevant files" in lower or ".py" in lower or ".md" in lower
    has_latest_user_direction = "latest user" in lower or "user direction" in lower or "直近" in text
    mentions_commit = "commit" in lower or "push" in lower
    skill_view_dump_detected = "skill_view" in lower and len(text) > 5000
    raw_tool_dump_detected = len(text) > 8000 and any(marker in lower for marker in ("tool output", "skill_view", "traceback", "total output lines"))
    likely_resumable = has_active_task and has_completed_actions and has_remaining_work and not raw_tool_dump_detected
    return {
        "has_active_task": has_active_task,
        "has_completed_actions": has_completed_actions,
        "has_remaining_work": has_remaining_work,
        "has_relevant_files": has_relevant_files,
        "has_latest_user_direction": has_latest_user_direction,
        "mentions_commit": mentions_commit,
        "raw_tool_dump_detected": raw_tool_dump_detected,
        "skill_view_dump_detected": skill_view_dump_detected,
        "likely_resumable": likely_resumable,
    }


def build_payload(model: str, focus_topic: str | None = None, *, variant: str = "current") -> dict:
    overrides = variant_overrides(variant)
    payload, _stats = build_codex_compact_payload(FIXTURE_MESSAGES, model=model, **{k: v for k, v in overrides.items() if k != "recent_tail_messages"})
    return payload


def build_payload_from_fixture(
    fixture: str | Path,
    *,
    model: str,
    focus_topic: str | None = None,
    max_tool_result_chars: int = 4000,
    max_input_item_chars: int | None = None,
    variant: str = "current",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    messages = load_session_messages(fixture)
    overrides = variant_overrides(variant)
    payload_kwargs = {k: v for k, v in overrides.items() if k != "recent_tail_messages"}
    payload, _stats = build_codex_compact_payload(
        messages,
        model=model,
        max_tool_output_chars=max_tool_result_chars,
        token_budget_chars=max_input_item_chars,
        **payload_kwargs,
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
    variant: str = "current",
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "dry_run": True,
        "variant": variant,
        "fixture": str(fixture) if fixture else None,
        "message_summary": summarize_messages(messages),
        "payload_summary": {
            "model": payload.get("model"),
            "input_items": len(payload.get("input") or []),
            "response_item_types": response_item_type_counts(payload.get("input") or []),
            "instruction_chars": len(payload.get("instructions") or ""),
            "tools": len(payload.get("tools") or []),
            "parallel_tool_calls": bool(payload.get("parallel_tool_calls")),
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
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="current", help="Payload/preprocessing parity variant for A/B smoke")
    parser.add_argument("--recent-tail-messages", type=int, default=None)
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
            variant=args.variant,
        )
    else:
        messages = FIXTURE_MESSAGES
        payload = build_payload(args.model, args.focus_topic or None, variant=args.variant)

    overrides = variant_overrides(args.variant)
    recent_tail_messages = args.recent_tail_messages
    if recent_tail_messages is None:
        recent_tail_messages = int(overrides.get("recent_tail_messages", 2))

    if not args.execute:
        print(json.dumps(
            dry_run_summary(payload, messages, fixture=args.fixture or None, compare_builtin=args.compare_builtin, variant=args.variant),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    config = CodexCompactConfig(auth_mode=args.auth_mode, model=args.model)
    response = CompactClient(config).compact(payload)
    replacement = compact_response_to_hermes_messages(
        response,
        messages,
        recent_tail_messages=recent_tail_messages,
    )
    replacement_text = "\n".join(str(message.get("content", "")) for message in replacement)
    print(json.dumps({
        "fixture": args.fixture or None,
        "variant": args.variant,
        "message_summary": summarize_messages(messages),
        "replacement": replacement,
        "handoff_quality": evaluate_handoff_quality(replacement_text),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
