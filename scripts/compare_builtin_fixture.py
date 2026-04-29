#!/usr/bin/env python3
"""Run Hermes built-in ContextCompressor against a JSONL fixture.

This intentionally lives as a manual smoke helper: it may call the configured
auxiliary compression model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERMES_REPO = Path.home() / ".hermes" / "hermes-agent"
for path in (ROOT, HERMES_REPO):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

from session_fixtures import load_session_messages, summarize_messages  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--focus-topic", default="")
    parser.add_argument("--current-tokens", type=int, default=200000)
    args = parser.parse_args(argv)

    from agent.context_compressor import ContextCompressor  # noqa: E402

    messages = load_session_messages(args.fixture)
    compressor = ContextCompressor(model=args.model, quiet_mode=True)
    replacement = compressor.compress(
        messages,
        current_tokens=args.current_tokens,
        focus_topic=args.focus_topic or None,
    )
    print(json.dumps({
        "engine": "builtin",
        "fixture": args.fixture,
        "message_summary": summarize_messages(messages),
        "replacement_summary": summarize_messages(replacement),
        "replacement": replacement,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
