#!/usr/bin/env python3
"""Export a Hermes session into a gitignored JSONL fixture directory.

This is a thin helper around `hermes sessions export`; it keeps private session
fixtures under tests/fixtures/private/ by default so they are not committed.
Use `--session-id` for one session, or omit it to export all sessions.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "tests" / "fixtures" / "private"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", default="", help="Optional Hermes session_id to export; omit to export all sessions")
    parser.add_argument("--source", default="", help="Optional source filter passed to `hermes sessions export --source`")
    parser.add_argument("--output", "-o", default="", help="Output JSONL path. Defaults to tests/fixtures/private/<session-id-or-all>.jsonl")
    args = parser.parse_args(argv)

    stem = args.session_id or "all-sessions"
    output = Path(args.output).expanduser() if args.output else DEFAULT_OUTPUT_DIR / f"{stem}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["hermes", "sessions", "export"]
    if args.session_id:
        command.extend(["--session-id", args.session_id])
    if args.source:
        command.extend(["--source", args.source])
    command.append(str(output))
    completed = subprocess.run(command, text=True)
    if completed.returncode != 0:
        return completed.returncode
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
