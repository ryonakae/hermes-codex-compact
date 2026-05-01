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
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client import CompactClient  # noqa: E402
from codex_native_fixture import load_codex_native_fixture  # noqa: E402
from compact_postprocess import compact_response_to_hermes_messages  # noqa: E402
from compact_preprocess import build_codex_compact_payload, estimate_response_item_visible_chars, response_item_type_counts  # noqa: E402
from config import CodexCompactConfig  # noqa: E402
from hermes_plaintext_fixture import load_hermes_plaintext_fixture, safe_metrics  # noqa: E402
from local_style_compact import build_local_style_payload  # noqa: E402
from message_ops import build_replacement_history  # noqa: E402
from session_fixtures import load_session_messages, summarize_messages  # noqa: E402
from tool_schemas import extract_tool_names_from_messages, minimal_fixture_tool_schemas  # noqa: E402

VARIANTS = {"current", "conversion-parity", "payload-parity", "preprocessing-parity", "instructed-remote", "instructed-tools-remote"}

HERMES_COMPACT_BASE_INSTRUCTIONS = """You are Hermes Agent, a coding and task-execution agent. You are compacting a prior agent session for future continuation. The input contains user requests, assistant progress, and structured tool calls/results. Preserve the user's goal, decisions, completed work, relevant files, commands, constraints, blockers, and next steps. Do not copy raw tool output unless it is necessary to resume."""

FIXTURE_MESSAGES = [
    {"role": "system", "content": "You are Hermes, a helpful coding agent."},
    {"role": "user", "content": "Build a tiny Hermes ContextEngine plugin."},
    {"role": "assistant", "content": "I created a plan and started implementing conversion helpers."},
    {"role": "tool", "tool_call_id": "call_1", "name": "pytest", "content": "25 tests passed"},
]


def apply_focus_topic(payload: Dict[str, Any], focus_topic: str | None) -> Dict[str, Any]:
    if not focus_topic:
        return payload
    topic = " ".join(str(focus_topic).split())[:500]
    if not topic:
        return payload
    payload = dict(payload)
    current = str(payload.get("instructions") or "").strip()
    focus_instruction = (
        "Compaction focus: prioritize preserving context needed to continue this task: "
        f"{topic}"
    )
    payload["instructions"] = f"{current}\n\n{focus_instruction}" if current else focus_instruction
    return payload


def variant_overrides(variant: str) -> Dict[str, Any]:
    if variant not in VARIANTS:
        raise ValueError(f"Unsupported smoke variant: {variant}")
    overrides: Dict[str, Any] = {}
    if variant in {"conversion-parity", "payload-parity", "preprocessing-parity", "instructed-remote", "instructed-tools-remote"}:
        overrides["message_shape"] = "core"
    if variant in {"payload-parity", "preprocessing-parity", "instructed-remote", "instructed-tools-remote"}:
        overrides["instruction_policy"] = "codex_base_only"
        overrides["parallel_tool_calls"] = True
    if variant in {"instructed-remote", "instructed-tools-remote"}:
        overrides["base_instructions"] = HERMES_COMPACT_BASE_INSTRUCTIONS
    if variant == "instructed-tools-remote":
        overrides["inject_fixture_tools"] = True
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


def build_payload(model: str, focus_topic: str | None = None, *, variant: str = "current", compact_path: str = "remote") -> dict:
    overrides = variant_overrides(variant)
    payload_kwargs = {k: v for k, v in overrides.items() if k not in {"recent_tail_messages", "inject_fixture_tools"}}
    tools = None
    if overrides.get("inject_fixture_tools"):
        tools = minimal_fixture_tool_schemas(extract_tool_names_from_messages(FIXTURE_MESSAGES))
    payload, _stats = build_codex_compact_payload(FIXTURE_MESSAGES, model=model, tools=tools, **payload_kwargs)
    payload = apply_focus_topic(payload, focus_topic)
    if compact_path == "local-style":
        payload = build_local_style_payload(payload)
    return payload


def build_payload_from_fixture(
    fixture: str | Path,
    *,
    model: str,
    focus_topic: str | None = None,
    max_tool_result_chars: int = 4000,
    max_input_item_chars: int | None = None,
    variant: str = "current",
    compact_path: str = "remote",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    messages = load_session_messages(fixture)
    overrides = variant_overrides(variant)
    payload_kwargs = {k: v for k, v in overrides.items() if k not in {"recent_tail_messages", "inject_fixture_tools"}}
    tools = None
    if overrides.get("inject_fixture_tools"):
        tools = minimal_fixture_tool_schemas(extract_tool_names_from_messages(messages))
    payload, _stats = build_codex_compact_payload(
        messages,
        model=model,
        tools=tools,
        max_tool_output_chars=max_tool_result_chars,
        token_budget_chars=max_input_item_chars,
        **payload_kwargs,
    )
    payload = apply_focus_topic(payload, focus_topic)
    if compact_path == "local-style":
        payload = build_local_style_payload(payload)
    return payload, messages


def build_payload_from_codex_native_fixture(path: Path | str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    fixture = load_codex_native_fixture(path)
    payload = fixture.payload
    items = payload.get("input") if isinstance(payload.get("input"), list) else []
    stats = {
        "input_items": len(items),
        "response_item_types": response_item_type_counts(items),
        "visible_chars": sum(
            estimate_response_item_visible_chars(item) for item in items if isinstance(item, dict)
        ),
        "instruction_chars": len(str(payload.get("instructions") or "")),
        "tools": len(payload.get("tools") or []),
        "codex_native_fixture": True,
    }
    return payload, stats, fixture.identity_headers


def build_payload_from_hermes_plaintext_fixture(path: Path | str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    fixture = load_hermes_plaintext_fixture(path)
    payload = fixture.payload
    stats = safe_metrics(payload)
    stats["hermes_plaintext_fixture"] = True
    return payload, stats, fixture.identity_headers


def config_with_identity_headers(config: CodexCompactConfig, headers: dict[str, str]) -> CodexCompactConfig:
    return replace(
        config,
        codex_session_id=headers.get("session_id", ""),
        codex_window_id=headers.get("x-codex-window-id", ""),
        codex_installation_id=headers.get("x-codex-installation-id", ""),
    )


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


def codex_native_dry_run_summary(
    payload: Dict[str, Any],
    stats: Dict[str, Any],
    identity_headers: Dict[str, str],
    *,
    fixture: str | Path,
) -> Dict[str, Any]:
    return {
        "dry_run": True,
        "codex_native_fixture": True,
        "fixture": str(fixture),
        "payload_summary": {
            "model": payload.get("model"),
            "input_items": stats.get("input_items", 0),
            "response_item_types": stats.get("response_item_types", {}),
            "visible_chars": stats.get("visible_chars", 0),
            "instruction_chars": stats.get("instruction_chars", 0),
            "tools": stats.get("tools", 0),
            "parallel_tool_calls": bool(payload.get("parallel_tool_calls")),
        },
        "identity_header_names": sorted(identity_headers),
        "note": "Native fixture dry-run omits raw input items and encrypted_content values.",
    }


def hermes_plaintext_dry_run_summary(
    payload: Dict[str, Any],
    stats: Dict[str, Any],
    identity_headers: Dict[str, str],
    *,
    fixture: str | Path,
) -> Dict[str, Any]:
    return {
        "dry_run": True,
        "hermes_plaintext_fixture": True,
        "fixture": str(fixture),
        "payload_summary": {
            "model": payload.get("model"),
            "input_items": stats.get("input_items", 0),
            "response_item_types": stats.get("response_item_types", {}),
            "visible_chars": stats.get("visible_chars", 0),
            "instruction_chars": stats.get("instruction_chars", 0),
            "tools": stats.get("tools", 0),
            "parallel_tool_calls": bool(payload.get("parallel_tool_calls")),
            "forbidden_encrypted_fields": stats.get("forbidden_encrypted_fields", 0),
        },
        "identity_header_names": sorted(identity_headers),
        "note": "Hermes plaintext fixture dry-run omits raw messages, raw tool output, and payload JSON.",
    }


def compact_response_safe_summary(response: Dict[str, Any]) -> Dict[str, Any]:
    output = response.get("output") if isinstance(response, dict) else None
    items = output if isinstance(output, list) else []
    return {
        "response_keys": sorted(response.keys()) if isinstance(response, dict) else [],
        "output_items": len(items),
        "output_item_types": response_item_type_counts([item for item in items if isinstance(item, dict)]),
        "has_opaque_compaction": any(
            isinstance(item, dict) and item.get("type") == "compaction" and bool(item.get("encrypted_content"))
            for item in items
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-mode", choices=["api_key", "codex_oauth", "auto"], default="api_key")
    parser.add_argument("--model", default="gpt-5.1-codex")
    parser.add_argument("--focus-topic", default="")
    parser.add_argument("--fixture", default="", help="Optional JSONL fixture exported from a Hermes session")
    parser.add_argument("--codex-native-fixture", default="", help="Ignored/private Codex-native compact fixture JSON to replay directly")
    parser.add_argument("--hermes-plaintext-fixture", default="", help="Ignored/private Hermes JSONL-derived plaintext compact fixture JSON to replay directly")
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="current", help="Payload/preprocessing parity variant for A/B smoke")
    parser.add_argument("--compact-path", choices=["remote", "local-style"], default="remote", help="Use /responses/compact payload or normal Responses local-style checkpoint prompt")
    parser.add_argument("--recent-tail-messages", type=int, default=None)
    parser.add_argument("--max-tool-result-chars", type=int, default=4000)
    parser.add_argument("--max-input-item-chars", type=int, default=0)
    parser.add_argument("--compare-builtin", action="store_true", help="Report built-in compressor comparability without changing runtime config")
    parser.add_argument("--execute", action="store_true", help="Actually call the remote compact endpoint")
    parser.add_argument("--dry-run", action="store_true", help="Explicit no-op flag; dry-run is the default unless --execute is set")
    args = parser.parse_args(argv)

    direct_fixtures = [bool(args.fixture), bool(args.codex_native_fixture), bool(args.hermes_plaintext_fixture)]
    if sum(direct_fixtures) > 1:
        parser.error("--fixture, --codex-native-fixture, and --hermes-plaintext-fixture are mutually exclusive")

    if args.codex_native_fixture:
        if args.compact_path != "remote":
            parser.error("--codex-native-fixture only supports --compact-path remote")
        if args.focus_topic:
            parser.error("--codex-native-fixture does not apply --focus-topic")
        payload, native_stats, identity_headers = build_payload_from_codex_native_fixture(args.codex_native_fixture)
        messages: List[Dict[str, Any]] = []
    elif args.hermes_plaintext_fixture:
        if args.compact_path != "remote":
            parser.error("--hermes-plaintext-fixture only supports --compact-path remote")
        if args.focus_topic:
            parser.error("--hermes-plaintext-fixture already contains instructions; do not combine with --focus-topic")
        payload, plaintext_stats, identity_headers = build_payload_from_hermes_plaintext_fixture(args.hermes_plaintext_fixture)
        messages = []
    elif args.fixture:
        payload, messages = build_payload_from_fixture(
            args.fixture,
            model=args.model,
            focus_topic=args.focus_topic or None,
            max_tool_result_chars=args.max_tool_result_chars,
            max_input_item_chars=args.max_input_item_chars or None,
            variant=args.variant,
            compact_path=args.compact_path,
        )
    else:
        messages = FIXTURE_MESSAGES
        payload = build_payload(args.model, args.focus_topic or None, variant=args.variant, compact_path=args.compact_path)

    overrides = variant_overrides(args.variant)
    recent_tail_messages = args.recent_tail_messages
    if recent_tail_messages is None:
        recent_tail_messages = int(overrides.get("recent_tail_messages", 2))

    if not args.execute and args.codex_native_fixture:
        print(json.dumps(
            codex_native_dry_run_summary(payload, native_stats, identity_headers, fixture=args.codex_native_fixture),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if not args.execute and args.hermes_plaintext_fixture:
        print(json.dumps(
            hermes_plaintext_dry_run_summary(payload, plaintext_stats, identity_headers, fixture=args.hermes_plaintext_fixture),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if not args.execute:
        print(json.dumps(
            dry_run_summary(payload, messages, fixture=args.fixture or None, compare_builtin=args.compare_builtin, variant=f"{args.variant}:{args.compact_path}"),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    config = CodexCompactConfig(auth_mode=args.auth_mode, model=args.model)
    if args.codex_native_fixture or args.hermes_plaintext_fixture:
        config = config_with_identity_headers(config, identity_headers)
    client = CompactClient(config)
    if args.codex_native_fixture:
        response = client.compact(payload)
        print(json.dumps({
            "fixture": args.codex_native_fixture,
            "codex_native_fixture": True,
            "response_summary": compact_response_safe_summary(response),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.hermes_plaintext_fixture:
        response = client.compact(payload)
        replacement = compact_response_to_hermes_messages(response, [], recent_tail_messages=0)
        print(json.dumps({
            "fixture": args.hermes_plaintext_fixture,
            "hermes_plaintext_fixture": True,
            "response_summary": compact_response_safe_summary(response),
            "replacement_messages": len(replacement),
        }, ensure_ascii=False, indent=2))
        return 0

    if args.compact_path == "local-style":
        response = client.responses(payload)
        output_text = response.get("output_text") or ""
        if not output_text:
            output_text = json.dumps(response.get("output") or response, ensure_ascii=False)
        replacement = [{"role": "assistant", "content": str(output_text)}]
    else:
        response = client.compact(payload)
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
