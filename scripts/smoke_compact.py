#!/usr/bin/env python3
"""Smoke test OpenAI/Codex responses/compact with a tiny fixture.

Default is dry-run to avoid accidental network/API usage:

    python scripts/smoke_compact.py --auth-mode api_key --execute
    python scripts/smoke_compact.py --auth-mode codex_oauth --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client import CompactClient  # noqa: E402
from config import CodexCompactConfig  # noqa: E402
from conversion import extract_compact_text, hermes_messages_to_compact_payload  # noqa: E402
from message_ops import build_replacement_history, prepare_for_compact  # noqa: E402

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-mode", choices=["api_key", "codex_oauth", "auto"], default="api_key")
    parser.add_argument("--model", default="gpt-5.1-codex")
    parser.add_argument("--focus-topic", default="")
    parser.add_argument("--execute", action="store_true", help="Actually call the remote compact endpoint")
    args = parser.parse_args(argv)

    payload = build_payload(args.model, args.focus_topic or None)
    if not args.execute:
        print(json.dumps({"dry_run": True, "payload": payload}, ensure_ascii=False, indent=2))
        return 0

    config = CodexCompactConfig(auth_mode=args.auth_mode, model=args.model)
    response = CompactClient(config).compact(payload)
    compact_text = extract_compact_text(response)
    replacement = build_replacement_history(FIXTURE_MESSAGES, compact_text, recent_tail_messages=1)
    print(json.dumps({"compact_text": compact_text, "replacement": replacement}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
