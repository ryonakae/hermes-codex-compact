# Codex Remote Native Parity Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Reframe `/responses/compact` as a Codex-native opaque checkpoint path, stop treating encrypted compaction output as a readable Hermes summary, and build a fair remote parity smoke path using Codex-native ResponseItem fixtures and session/window identity.

**Architecture:** Keep `context.engine` unchanged and keep the plugin standalone. Add explicit postprocess semantics for opaque `ResponseItem::Compaction { encrypted_content }`, then add a Codex-native fixture/replay path that can send native ResponseItems, encrypted reasoning/compaction items, exact-ish request fields, and Codex identity headers without committing private data.

**Tech Stack:** Python 3.11, pytest, Hermes standalone ContextEngine plugin, OpenAI/Codex Responses payloads, ignored private fixtures under `tests/fixtures/private/`, Codex OAuth via Hermes resolver.

---

## Scope

This plan implements the user's selected items 1〜4 only:

1. Treat `/responses/compact` as a Codex-native opaque checkpoint path, not a readable summary endpoint.
2. Add parity tests/docs for `ResponseItem::Compaction { encrypted_content }` so postprocess does not pretend it extracted plaintext.
3. Add a Codex-native fixture replay path for raw ResponseItem history, including encrypted reasoning and compaction items.
4. Add session/window header shape support for remote compact parity smoke.

Explicitly out of scope:

- Do not review or improve `instructed-tools-local-style` output in this plan.
- Do not switch production runtime `context.engine`.
- Do not add built-in compressor fallback.
- Do not edit Hermes core or Codex upstream.
- Do not commit raw Codex/Hermes session payloads, raw responses, OAuth tokens, API keys, Authorization headers, account IDs, emails, or private tool output.

---

## Current Evidence

Official Codex main checked on 2026-05-01:

```text
openai/codex main f50c02d7bcd4c06a23173389da8ed2c68c03d81d
```

Relevant official behavior:

- Remote compact calls `/responses/compact`.
- Successful compact output is modeled as `ResponseItem::Compaction { encrypted_content }` with serde alias `compaction_summary`.
- The compaction item is mounted back into Codex-native history, not converted to a visible user/assistant summary.
- Regular `/responses` requests include `reasoning.encrypted_content` when reasoning is enabled.
- Remote compact sends Codex identity/session headers such as `x-codex-installation-id`, `x-codex-window-id`, and `session_id`.

Plugin gap today:

- `compact_postprocess.py` keeps `type=compaction` but only extracts `summary/content/text`; encrypted-only compaction currently falls through ambiguously.
- Existing real fixture is Hermes JSONL and lossy: no native encrypted reasoning items, no native compaction items, no exact Codex `ToolSpec`, no Codex window/session identity.
- `client.py` has Codex auth headers but not Codex identity/session header overrides.

---

## Acceptance Criteria

Run from plugin repo root:

```bash
python -m pytest -q
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py codex_native_fixture.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py tests/*.py
```

Expected:

```text
all tests pass, 1 skipped allowed
py_compile OK
```

Plugin discovery still works:

```bash
cd ~/.hermes/hermes-agent
python - <<'PY'
from hermes_cli.plugins import PluginManager
pm = PluginManager()
pm.discover_and_load(force=True)
loaded = pm._plugins.get('hermes-codex-compact')
print('found=', bool(loaded))
print('enabled=', getattr(loaded, 'enabled', None))
print('error=', getattr(loaded, 'error', None))
PY
```

Expected:

```text
found= True
enabled= True
error= None
```

Private artifact safety:

```bash
git status --short --ignored
```

Expected:

```text
tracked tree clean after commits
only cache/private fixture paths ignored
```

---

## Task 1: Make Opaque Remote Compaction Explicit

**Objective:** Ensure encrypted-only remote compaction output is never treated as a readable Hermes summary.

**Files:**

- Modify: `compact_postprocess.py`
- Modify: `tests/test_compact_postprocess.py`
- Modify: `README.md`

**Step 1: Write failing tests**

Add tests to `tests/test_compact_postprocess.py`:

```python
import pytest

from compact_postprocess import (
    OpaqueRemoteCompactionError,
    compact_response_to_hermes_messages,
    response_item_to_hermes_message,
    should_keep_compacted_response_item,
)


def test_encrypted_only_compaction_is_opaque_not_readable_summary():
    item = {"type": "compaction", "encrypted_content": "ENCRYPTED_COMPACTION_SUMMARY"}

    assert should_keep_compacted_response_item(item) is False
    assert response_item_to_hermes_message(item) is None


def test_remote_compact_encrypted_only_response_fails_closed():
    response = {
        "output": [
            {"type": "compaction", "encrypted_content": "ENCRYPTED_COMPACTION_SUMMARY"},
        ]
    }

    with pytest.raises(OpaqueRemoteCompactionError) as exc:
        compact_response_to_hermes_messages(response, original_messages=[])

    assert "opaque Codex compaction checkpoint" in str(exc.value)
    assert "encrypted_content" in str(exc.value)
```

Keep existing readable `output_text` and message-output tests passing.

**Step 2: Verify RED**

Run:

```bash
python -m pytest tests/test_compact_postprocess.py -q
```

Expected: FAIL because `OpaqueRemoteCompactionError` does not exist and encrypted compaction handling is still ambiguous.

**Step 3: Implement minimal code**

In `compact_postprocess.py` add:

```python
class OpaqueRemoteCompactionError(RuntimeError):
    """Raised when Codex remote compact returns only an opaque checkpoint."""


def is_opaque_compaction_item(item: Dict[str, Any]) -> bool:
    return (
        isinstance(item, dict)
        and item.get("type") == "compaction"
        and isinstance(item.get("encrypted_content"), str)
        and not any(item.get(key) for key in ("summary", "content", "text"))
    )
```

Update `should_keep_compacted_response_item()`:

```python
if item_type == "compaction":
    return not is_opaque_compaction_item(item)
```

Update `compact_response_to_hermes_messages()` before fallback extraction:

```python
output = response.get("output")
if isinstance(output, list) and any(is_opaque_compaction_item(item) for item in output):
    raise OpaqueRemoteCompactionError(
        "Codex remote compact returned an opaque Codex compaction checkpoint "
        "(`encrypted_content`) rather than readable summary text. "
        "Do not use this as Hermes replacement history without a Codex-native replay path."
    )
```

Do not include encrypted content in the exception message.

**Step 4: Verify GREEN**

Run:

```bash
python -m pytest tests/test_compact_postprocess.py -q
```

Expected: PASS.

**Step 5: Document behavior**

In `README.md`, add a short section under remote compact notes:

```markdown
### Remote Compact Opaque Checkpoints

Codex `/responses/compact` may return `type: compaction` with only `encrypted_content`. The plugin treats this as an opaque Codex-native checkpoint and fails closed instead of converting it into a fake readable Hermes summary. Use the Codex-native fixture/replay smoke path to evaluate this mode.
```

**Step 6: Commit**

```bash
git add compact_postprocess.py tests/test_compact_postprocess.py README.md
git commit -m "fix: fail closed on opaque codex compaction"
```

---

## Task 2: Add Codex-Native Fixture Model

**Objective:** Represent Codex-native compact fixtures without depending on Hermes JSONL message export.

**Files:**

- Create: `codex_native_fixture.py`
- Create: `tests/test_codex_native_fixture.py`
- Create: `tests/fixtures/codex_native_minimal.json`
- Modify: `.gitignore` if needed to keep `tests/fixtures/private/` ignored

**Fixture Shape:**

Public synthetic fixture must contain no real session data:

```json
{
  "metadata": {
    "source": "synthetic-codex-native",
    "model": "gpt-5.5",
    "session_id": "00000000-0000-4000-8000-000000000001",
    "window_id": "00000000-0000-4000-8000-000000000001:0",
    "installation_id": "00000000-0000-4000-8000-000000000002"
  },
  "request": {
    "model": "gpt-5.5",
    "instructions": "You are Codex, a coding agent based on GPT-5.",
    "input": [
      {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Implement feature X"}]},
      {"type": "reasoning", "summary": [], "encrypted_content": "ENCRYPTED_REASONING_SYNTHETIC"},
      {"type": "function_call", "name": "shell", "arguments": "{\"cmd\":\"pytest -q\"}", "call_id": "call_synthetic"},
      {"type": "function_call_output", "call_id": "call_synthetic", "output": "3 passed"},
      {"type": "compaction", "encrypted_content": "ENCRYPTED_PREVIOUS_COMPACTION_SYNTHETIC"}
    ],
    "tools": [],
    "parallel_tool_calls": true,
    "reasoning": {"effort": "medium", "summary": "auto"},
    "text": null
  }
}
```

**Step 1: Write failing tests**

Create `tests/test_codex_native_fixture.py`:

```python
from pathlib import Path

from codex_native_fixture import load_codex_native_fixture


def test_load_codex_native_fixture_preserves_encrypted_items():
    fixture = load_codex_native_fixture(Path("tests/fixtures/codex_native_minimal.json"))

    assert fixture.payload["model"] == "gpt-5.5"
    assert any(item["type"] == "reasoning" and item.get("encrypted_content") for item in fixture.payload["input"])
    assert any(item["type"] == "compaction" and item.get("encrypted_content") for item in fixture.payload["input"])


def test_load_codex_native_fixture_derives_identity_headers():
    fixture = load_codex_native_fixture(Path("tests/fixtures/codex_native_minimal.json"))

    assert fixture.identity_headers == {
        "session_id": "00000000-0000-4000-8000-000000000001",
        "x-codex-window-id": "00000000-0000-4000-8000-000000000001:0",
        "x-codex-installation-id": "00000000-0000-4000-8000-000000000002",
    }
```

**Step 2: Verify RED**

Run:

```bash
python -m pytest tests/test_codex_native_fixture.py -q
```

Expected: FAIL because module/fixture do not exist.

**Step 3: Implement fixture loader**

Create `codex_native_fixture.py`:

```python
"""Codex-native fixture loading for remote compact parity smoke."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class CodexNativeFixture:
    payload: Dict[str, Any]
    identity_headers: Dict[str, str]
    metadata: Dict[str, Any]


def _string_metadata(metadata: Dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else ""


def load_codex_native_fixture(path: Path | str) -> CodexNativeFixture:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Codex-native fixture must be a JSON object")
    request = data.get("request")
    if not isinstance(request, dict):
        raise ValueError("Codex-native fixture requires object field `request`")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    payload = copy.deepcopy(request)
    headers = {
        "session_id": _string_metadata(metadata, "session_id"),
        "x-codex-window-id": _string_metadata(metadata, "window_id"),
        "x-codex-installation-id": _string_metadata(metadata, "installation_id"),
    }
    headers = {key: value for key, value in headers.items() if value}
    return CodexNativeFixture(payload=payload, identity_headers=headers, metadata=dict(metadata))
```

**Step 4: Verify GREEN**

Run:

```bash
python -m pytest tests/test_codex_native_fixture.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add codex_native_fixture.py tests/test_codex_native_fixture.py tests/fixtures/codex_native_minimal.json .gitignore
git commit -m "feat: add codex native compact fixtures"
```

---

## Task 3: Add Codex Identity Header Overrides

**Objective:** Allow remote compact smoke to send Codex-like non-secret identity/session headers.

**Files:**

- Modify: `client.py`
- Modify: `config.py`
- Create or modify: `tests/test_client_headers.py`
- Modify: `README.md`

**Step 1: Write failing tests**

Create `tests/test_client_headers.py`:

```python
from client import CompactClient
from config import CodexCompactConfig


def test_codex_oauth_request_includes_identity_headers_from_config():
    config = CodexCompactConfig(
        auth_mode="codex_oauth",
        codex_session_id="sess_1",
        codex_window_id="sess_1:0",
        codex_installation_id="install_1",
    )
    client = CompactClient(
        config,
        codex_resolver=lambda: {"api_key": "token", "base_url": "https://example.test/codex"},
        codex_header_builder=lambda token: {"Authorization": f"Bearer {token}"},
    )

    url, headers = client._codex_oauth_request(compact=True)

    assert url == "https://example.test/codex/responses/compact"
    assert headers["session_id"] == "sess_1"
    assert headers["x-codex-window-id"] == "sess_1:0"
    assert headers["x-codex-installation-id"] == "install_1"


def test_api_key_request_does_not_add_codex_identity_headers():
    config = CodexCompactConfig(
        auth_mode="api_key",
        openai_api_key="sk-test",
        codex_session_id="sess_1",
        codex_window_id="sess_1:0",
        codex_installation_id="install_1",
    )
    client = CompactClient(config)

    _, headers = client._api_key_request(compact=True)

    assert "session_id" not in headers
    assert "x-codex-window-id" not in headers
    assert "x-codex-installation-id" not in headers
```

**Step 2: Verify RED**

Run:

```bash
python -m pytest tests/test_client_headers.py -q
```

Expected: FAIL because config fields do not exist and headers are not injected.

**Step 3: Add config fields**

In `config.py` add dataclass fields:

```python
codex_session_id: str = ""
codex_window_id: str = ""
codex_installation_id: str = ""
```

Ensure `load_config()` reads them from `codex_compact:` YAML like other fields.

**Step 4: Add header injection**

In `client.py` add helper:

```python
def _codex_identity_headers(self) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if self.config.codex_session_id:
        headers["session_id"] = self.config.codex_session_id
    if self.config.codex_window_id:
        headers["x-codex-window-id"] = self.config.codex_window_id
    if self.config.codex_installation_id:
        headers["x-codex-installation-id"] = self.config.codex_installation_id
    return headers
```

Call it only in `_codex_oauth_request()`:

```python
headers.update(self._codex_identity_headers())
```

Do not add these headers to public OpenAI API key mode unless there is later evidence that official OpenAI endpoint expects them.

**Step 5: Verify GREEN**

Run:

```bash
python -m pytest tests/test_client_headers.py -q
python -m pytest tests/test_client_streaming.py tests/test_client_headers.py -q
```

Expected: PASS.

**Step 6: Document config**

In `README.md` add:

```yaml
codex_compact:
  auth_mode: codex_oauth
  codex_session_id: ""        # optional, parity smoke only
  codex_window_id: ""         # optional, parity smoke only
  codex_installation_id: ""   # optional, parity smoke only
```

Mention these are not secrets but can still correlate sessions, so avoid logging them in public artifacts.

**Step 7: Commit**

```bash
git add client.py config.py tests/test_client_headers.py README.md
git commit -m "feat: add codex compact identity headers"
```

---

## Task 4: Wire Codex-Native Fixture Replay Into Smoke Script

**Objective:** Let `scripts/smoke_compact.py` send a Codex-native fixture payload directly to `/responses/compact` with fixture identity headers.

**Files:**

- Modify: `scripts/smoke_compact.py`
- Modify: `tests/test_smoke_fixture.py`
- Modify: `README.md`

**Step 1: Write failing tests**

Add to `tests/test_smoke_fixture.py`:

```python
from pathlib import Path

from codex_native_fixture import load_codex_native_fixture
from scripts.smoke_compact import build_payload_from_codex_native_fixture, config_with_identity_headers
from config import CodexCompactConfig


def test_build_payload_from_codex_native_fixture_preserves_native_items():
    fixture = Path("tests/fixtures/codex_native_minimal.json")

    payload, stats, identity_headers = build_payload_from_codex_native_fixture(fixture)

    assert payload["model"] == "gpt-5.5"
    assert any(item["type"] == "reasoning" for item in payload["input"])
    assert any(item["type"] == "compaction" for item in payload["input"])
    assert stats["input_items"] == len(payload["input"])
    assert identity_headers["session_id"]


def test_config_with_identity_headers_does_not_mutate_original_config():
    base = CodexCompactConfig(auth_mode="codex_oauth")
    fixture = load_codex_native_fixture(Path("tests/fixtures/codex_native_minimal.json"))

    updated = config_with_identity_headers(base, fixture.identity_headers)

    assert base.codex_session_id == ""
    assert updated.codex_session_id == fixture.identity_headers["session_id"]
    assert updated.codex_window_id == fixture.identity_headers["x-codex-window-id"]
```

**Step 2: Verify RED**

Run:

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

Expected: FAIL because helper functions do not exist.

**Step 3: Implement payload helper**

In `scripts/smoke_compact.py` import:

```python
from dataclasses import replace
from codex_native_fixture import load_codex_native_fixture
from compact_preprocess import response_item_type_counts, estimate_response_item_visible_chars
```

Add:

```python
def build_payload_from_codex_native_fixture(path: Path | str):
    fixture = load_codex_native_fixture(path)
    payload = fixture.payload
    items = payload.get("input") if isinstance(payload.get("input"), list) else []
    stats = {
        "input_items": len(items),
        "response_item_types": response_item_type_counts(items),
        "visible_chars": sum(estimate_response_item_visible_chars(item) for item in items if isinstance(item, dict)),
        "instruction_chars": len(str(payload.get("instructions") or "")),
        "tools": len(payload.get("tools") or []),
        "codex_native_fixture": True,
    }
    return payload, stats, fixture.identity_headers


def config_with_identity_headers(config: CodexCompactConfig, headers: dict[str, str]) -> CodexCompactConfig:
    return replace(
        config,
        codex_session_id=headers.get("session_id", ""),
        codex_window_id=headers.get("x-codex-window-id", ""),
        codex_installation_id=headers.get("x-codex-installation-id", ""),
    )
```

**Step 4: Add CLI option**

Add parser arg:

```python
parser.add_argument("--codex-native-fixture", default="", help="Ignored/private Codex-native compact fixture JSON to replay directly")
```

Execution behavior:

- If `--codex-native-fixture` is present, do not also require `--fixture`.
- Build payload through `build_payload_from_codex_native_fixture()`.
- Apply identity headers by replacing config before creating `CompactClient`.
- Force remote compact path for this mode unless `--dry-run` only.
- Do not apply `--variant`, `--focus-topic`, or local-style prompt transformations to native payloads.
- Dry-run should print only safe metrics: item counts, type counts, instruction chars, tool count, header names present. Do not dump raw input items.

**Step 5: Verify GREEN**

Run:

```bash
python -m pytest tests/test_smoke_fixture.py tests/test_codex_native_fixture.py -q
```

Expected: PASS.

**Step 6: Dry-run public synthetic fixture**

Run:

```bash
python scripts/smoke_compact.py --codex-native-fixture tests/fixtures/codex_native_minimal.json --dry-run
```

Expected safe output includes:

```text
codex_native_fixture=True
response_item_types includes reasoning and compaction
identity header names present
no raw encrypted_content printed
```

**Step 7: Document usage**

In `README.md` add:

```bash
python scripts/smoke_compact.py \
  --codex-native-fixture tests/fixtures/private/codex-native-real.json \
  --execute
```

Document required fixture fields and safety rules:

- `request` is the compact payload body.
- `metadata.session_id`, `metadata.window_id`, and `metadata.installation_id` become headers.
- Put real fixtures only under `tests/fixtures/private/`.
- Do not commit raw native fixtures or response outputs.
- Do not use this mode to create Hermes replacement history; it is a parity smoke tool.

**Step 8: Commit**

```bash
git add scripts/smoke_compact.py tests/test_smoke_fixture.py README.md
git commit -m "feat: replay codex native compact fixtures"
```

---

## Final Verification And Plan Update

**Objective:** Verify all selected 1〜4 work, update the existing quality plan, and push.

**Files:**

- Modify: `.hermes/plans/2026-04-30-codex-compact-next-quality-plan.md`
- Modify: `.hermes/plans/2026-05-01-codex-remote-native-parity.md` if implementation discovers corrections

**Step 1: Full tests**

Run:

```bash
python -m pytest -q
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py codex_native_fixture.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py tests/*.py
```

Expected: all tests pass, 1 skipped allowed.

**Step 2: Plugin discovery**

Run:

```bash
cd ~/.hermes/hermes-agent
python - <<'PY'
from hermes_cli.plugins import PluginManager
pm = PluginManager()
pm.discover_and_load(force=True)
loaded = pm._plugins.get('hermes-codex-compact')
print('found=', bool(loaded))
print('enabled=', getattr(loaded, 'enabled', None))
print('error=', getattr(loaded, 'error', None))
PY
```

Expected:

```text
found= True
enabled= True
error= None
```

**Step 3: Update existing plan**

Update `.hermes/plans/2026-04-30-codex-compact-next-quality-plan.md`:

- Mark remote compact as opaque Codex-native checkpoint path.
- Link this plan.
- State that Hermes JSONL fixture should no longer be used to judge remote compact quality.
- State that local-style review is intentionally not part of this implementation.

**Step 4: Commit docs if changed**

```bash
git add .hermes/plans/2026-04-30-codex-compact-next-quality-plan.md .hermes/plans/2026-05-01-codex-remote-native-parity.md
git commit -m "docs: update codex native compact parity plan"
```

Skip commit if no files changed.

**Step 5: Push**

```bash
git push
```

**Step 6: Final status**

Run:

```bash
git status --short --ignored
git log --oneline -8
```

Expected:

```text
tracked tree clean
ignored private/cache paths only
```

---

## Implementation Status

Implemented on 2026-05-01.

Commits:

```text
02e1195 fix: fail closed on opaque codex compaction
9b499f7 feat: add codex native compact fixtures
f2890d2 feat: add codex compact identity headers
092afe7 feat: replay codex native compact fixtures
```

Verification:

```text
python -m pytest -q
93 passed, 1 skipped

python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py codex_native_fixture.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py tests/*.py
OK

Plugin discovery:
found= True
enabled= True
error= None
```

Notes:

- `--dry-run` is now accepted explicitly even though dry-run remains the default without `--execute`.
- Codex-native dry-run output reports only safe metrics and header names; it omits raw input items and encrypted values.
- Execute mode for Codex-native fixtures returns a safe response summary, not Hermes replacement history.

---

## Open Question For Execution

How to obtain the first real Codex-native private fixture is intentionally not automated in this plan. The implementation supports an ignored JSON file with the documented shape. After that, a separate small investigation can decide the least invasive capture method from Codex CLI traces or debug output without touching credentials or committing raw session data.
