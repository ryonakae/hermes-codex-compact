"""Local-style Codex compaction payload helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "templates" / "compact"


def load_compact_templates(template_dir: Path | None = None) -> Dict[str, str]:
    base = template_dir or TEMPLATE_DIR
    prompt = (base / "prompt.md").read_text(encoding="utf-8")
    summary_prefix = (base / "summary_prefix.md").read_text(encoding="utf-8")
    return {"prompt": prompt, "summary_prefix": summary_prefix}


def build_local_style_payload(remote_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normal Responses payload that asks the model to summarize history.

    The remote compact endpoint receives a special `/responses/compact` request.
    Codex also has a local-style compaction path that uses an explicit checkpoint
    prompt through the normal Responses inference path. This helper builds that
    second shape without mutating the original payload.
    """
    templates = load_compact_templates()
    payload = dict(remote_payload)
    input_items = list(remote_payload.get("input") or [])
    compact_prompt = f"{templates['prompt'].rstrip()}\n\n{templates['summary_prefix'].rstrip()}"
    input_items.append({"type": "message", "role": "user", "content": compact_prompt})
    payload["input"] = input_items
    return payload
