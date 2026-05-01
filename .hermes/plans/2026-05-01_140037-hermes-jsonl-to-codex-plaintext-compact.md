# Hermes JSONL → Codex Plaintext Compact Fixture Plan

> **Plan only.** Do not switch `context.engine`, do not run this as the runtime compressor, and do not treat this as Codex-native encrypted parity.

## Goal

Build a safe, testable experiment that converts ignored/private Hermes session JSONL exports into a Codex Responses-style **plaintext-only** compact request fixture, then optionally sends that fixture to `/responses/compact` to learn whether Codex compact can accept and use Hermes-derived history without native `encrypted_content` state.

This plan intentionally does **not** try to synthesize Codex-native encrypted checkpoint state. Hermes JSONL cannot reconstruct valid `reasoning.encrypted_content` or `type: compaction` encrypted payloads, and fake encrypted values are rejected by the backend.

## Non-goals

- Do not change production `context.engine`.
- Do not claim Codex-native parity from this path.
- Do not fabricate `encrypted_content`.
- Do not commit real session JSONL, raw compact payloads, raw API responses, OAuth tokens, authorization headers, private tool output, account IDs, emails, or Slack/Gmail content.
- Do not re-open local-style quality improvement work in this plan.
- Do not edit Hermes core.

## Naming

Use explicit naming so future reports do not confuse the result with real Codex-native replay:

- Feature label: `hermes-jsonl-plaintext-compact`
- Fixture helper: `hermes_plaintext_fixture.py`
- Script: `scripts/convert_hermes_jsonl_to_codex_fixture.py`
- Smoke mode: `--hermes-plaintext-fixture`
- Report wording: `plaintext compact compatibility`, not `codex-native parity`

## Implementation Status

Implementation status on 2026-05-01: completed. The plaintext fixture loader, JSONL converter, smoke replay support, README documentation, and private real-session compatibility smoke were implemented. The real plaintext fixture smoke used only safe metrics and showed `/responses/compact` accepted the converted Hermes history, returning `message:2` and `compaction_summary:1` output items with no opaque encrypted compaction; postprocess produced 2 replacement messages.

Relevant implementation files:

- `hermes_plaintext_fixture.py`
- `scripts/convert_hermes_jsonl_to_codex_fixture.py`
- `scripts/smoke_compact.py`
- `tests/test_hermes_plaintext_fixture.py`
- `tests/test_convert_hermes_jsonl_to_codex_fixture.py`
- `tests/test_smoke_fixture.py`

## Current Context

Existing repo: `/Users/ryo.nakae/.hermes/plugins/hermes-codex-compact`

Relevant existing files:

- `session_fixtures.py` — loads Hermes JSONL session fixtures.
- `responses_conversion.py` — converts Hermes/OpenAI-style messages to Responses items.
- `compact_preprocess.py` — prepares compact input / trimming behavior.
- `tool_schemas.py` — derives tool schemas where possible.
- `codex_native_fixture.py` — loads Codex-native replay fixtures with encrypted items preserved.
- `scripts/smoke_compact.py` — can dry-run or execute compact smoke.
- `tests/fixtures/private/` — ignored private fixture location.

Recent evidence:

- Synthetic encrypted Codex-native fixture reached the backend but failed with `invalid_encrypted_content`, confirming fake encrypted state is not acceptable.
- Error redaction was improved in `e530d41 fix: redact encrypted compact error fragments`.
- Existing remote native parity plan is `.hermes/plans/2026-05-01-codex-remote-native-parity.md`.

## Proposed Approach

Create a separate plaintext fixture path:

```text
Hermes session JSONL
  → Hermes/OpenAI-format messages
  → Codex Responses-style input items
  → compact request fixture without encrypted_content
  → safe dry-run metrics
  → optional /responses/compact execution
```

The converter should preserve as much structure as is safely available:

- user / assistant text messages
- tool calls as `function_call`
- tool results as `function_call_output`
- assistant final text as message output
- recent tail priority metadata / instructions
- approximate tools list, if recoverable

But it must omit or reject:

- `reasoning.encrypted_content`
- `type: compaction` encrypted items
- raw secrets in output files
- unbounded tool output dumps

## Acceptance Criteria

From repo root:

```bash
python -m pytest -q
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py codex_native_fixture.py hermes_plaintext_fixture.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py scripts/convert_hermes_jsonl_to_codex_fixture.py tests/*.py
```

Expected:

```text
all tests pass, existing skipped tests allowed
py_compile OK
```

Plugin discovery must still pass:

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

## Task 1: Add Plaintext Fixture Model

**Objective:** Represent a converted Hermes JSONL compact fixture as plaintext-only data and make encrypted fields impossible by default.

**Files:**

- Create: `hermes_plaintext_fixture.py`
- Create: `tests/test_hermes_plaintext_fixture.py`
- Create: `tests/fixtures/hermes_plaintext_minimal.json`

**Tests first:**

Add tests that verify:

1. Loading a plaintext fixture returns `payload`, `metadata`, and safe `identity_headers`.
2. Any `encrypted_content` anywhere under `request.input` raises `ValueError`.
3. Any `type: compaction` item raises `ValueError`, unless it is later explicitly supported without encrypted content.
4. `safe_metrics()` returns counts only, not raw text.

**Implementation notes:**

- Use a dataclass similar to `CodexNativeFixture`, but with stricter validation.
- Add recursive scanning for forbidden keys/types.
- Keep metadata non-secret and optional.
- Preserve payload exactly after validation so smoke execution can send it.

**Verification:**

```bash
python -m pytest tests/test_hermes_plaintext_fixture.py -q
```

**Commit:**

```bash
git add hermes_plaintext_fixture.py tests/test_hermes_plaintext_fixture.py tests/fixtures/hermes_plaintext_minimal.json
git commit -m "feat: add hermes plaintext compact fixtures"
```

## Task 2: Convert Hermes JSONL to Plaintext Compact Fixture

**Objective:** Add a script that reads a Hermes session JSONL export and writes a private plaintext Codex compact request fixture.

**Files:**

- Create: `scripts/convert_hermes_jsonl_to_codex_fixture.py`
- Create: `tests/test_convert_hermes_jsonl_to_codex_fixture.py`
- Possibly modify: `responses_conversion.py`
- Possibly modify: `compact_preprocess.py`
- Possibly modify: `tool_schemas.py`

**CLI shape:**

```bash
python scripts/convert_hermes_jsonl_to_codex_fixture.py \
  --input tests/fixtures/private/real_session.jsonl \
  --output tests/fixtures/private/hermes-plaintext-real.compact.json \
  --model gpt-5.5 \
  --focus-topic 'Hermes ContextEngine plugin real-session compression test' \
  --max-tool-output-chars 4000 \
  --recent-tail-messages 12
```

**Important:** `--focus-topic` must actually influence the compact instructions. A previous smoke path accepted it but did not pass it into the payload builder, which made quality evaluation weaker.

**Payload shape:**

```json
{
  "metadata": {
    "source": "hermes-jsonl-plaintext",
    "source_file": "[basename only]",
    "model": "gpt-5.5",
    "focus_topic": "...",
    "encrypted_content": false
  },
  "request": {
    "model": "gpt-5.5",
    "instructions": "...",
    "input": [],
    "tools": [],
    "parallel_tool_calls": true,
    "reasoning": {"effort": "medium", "summary": "auto"},
    "text": null
  }
}
```

**Conversion rules:**

- User messages → `type: message`, `role: user`, `content: [{type: input_text, text: ...}]`
- Assistant text → `type: message`, `role: assistant`, output text content if supported by current converter
- Tool calls → `type: function_call`, preserving `call_id`, `name`, and JSON-string `arguments`
- Tool results → `type: function_call_output`, preserving `call_id` and bounded `output`
- Non-text or huge content → summarized/truncated with explicit marker, not silently dropped
- Unknown shapes → count in metadata warnings; fail only if they would corrupt tool-call pairing

**Recent-tail instruction:**

Include an instruction block like:

```text
Recent Tail Priority: Preserve the latest explicit user direction, implementation state, pushed commits, failing tests, and next action. If older plans conflict with recent user instructions, follow the recent user instructions.
```

**Safety:**

- Default output path should be under `tests/fixtures/private/` unless explicitly overridden.
- Refuse to write outside `tests/fixtures/private/` unless `--allow-public-output` is passed.
- Never write raw API responses.
- Do not log raw messages by default; print metrics only.

**Tests first:**

Use a tiny synthetic Hermes JSONL fixture and assert:

- generated fixture has no `encrypted_content`
- focus topic appears in `instructions`
- tool call/output pair survives
- large tool output is bounded
- output metadata contains counts and warnings

**Verification:**

```bash
python -m pytest tests/test_convert_hermes_jsonl_to_codex_fixture.py tests/test_responses_conversion.py tests/test_compact_preprocess.py -q
```

**Commit:**

```bash
git add scripts/convert_hermes_jsonl_to_codex_fixture.py tests/test_convert_hermes_jsonl_to_codex_fixture.py responses_conversion.py compact_preprocess.py tool_schemas.py
git commit -m "feat: convert hermes jsonl to plaintext compact fixtures"
```

## Task 3: Add Smoke Support for Hermes Plaintext Fixtures

**Objective:** Let `scripts/smoke_compact.py` dry-run and optionally execute these converted plaintext fixtures.

**Files:**

- Modify: `scripts/smoke_compact.py`
- Modify: `tests/test_smoke_fixture.py`
- Possibly modify: `client.py` only if payload execution currently assumes native fixture shape

**CLI shape:**

Dry-run:

```bash
python scripts/smoke_compact.py \
  --hermes-plaintext-fixture tests/fixtures/private/hermes-plaintext-real.compact.json \
  --dry-run
```

Execute:

```bash
python scripts/smoke_compact.py \
  --auth-mode codex_oauth \
  --hermes-plaintext-fixture tests/fixtures/private/hermes-plaintext-real.compact.json \
  --execute
```

**Dry-run output must include only safe metrics:**

- source label
- model
- input item count
- item type counts
- tool count
- instruction char count
- estimated text/tool-output char counts
- forbidden encrypted fields count, expected `0`
- header names only, if any

**Dry-run output must not include:**

- raw user text
- raw assistant text
- raw tool output
- raw payload JSON
- raw response JSON
- encrypted values
- Authorization header values

**Execution behavior:**

- If backend returns plaintext readable compact output, run existing postprocess and report safe summary metrics.
- If backend returns opaque `type: compaction`, fail closed with the existing `OpaqueRemoteCompactionError` path and report that this endpoint did not produce Hermes-readable replacement history.
- If backend rejects plaintext input, report status/category without raw body leakage.

**Tests first:**

Add tests that:

- dry-run for plaintext fixture prints metrics and no raw content
- `--hermes-plaintext-fixture` and `--codex-native-fixture` are mutually exclusive
- execution path passes fixture payload unchanged to fake client

**Verification:**

```bash
python -m pytest tests/test_smoke_fixture.py tests/test_client_payload.py -q
```

**Commit:**

```bash
git add scripts/smoke_compact.py tests/test_smoke_fixture.py tests/test_client_payload.py
git commit -m "feat: smoke test hermes plaintext compact fixtures"
```

## Task 4: Run Private Real-Session Compatibility Smoke

**Objective:** Use an ignored Hermes real session JSONL to see whether `/responses/compact` accepts plaintext-only converted history.

**Prerequisite:** A real Hermes session export under `tests/fixtures/private/`, for example:

```bash
hermes sessions export tests/fixtures/private/real-session.jsonl
```

If no suitable export exists, use the existing export script or `hermes sessions export` from the active Hermes install. Do not commit the file.

**Commands:**

Convert:

```bash
python scripts/convert_hermes_jsonl_to_codex_fixture.py \
  --input tests/fixtures/private/real-session.jsonl \
  --output tests/fixtures/private/hermes-plaintext-real.compact.json \
  --model gpt-5.5 \
  --focus-topic 'Hermes ContextEngine plugin real-session compression test' \
  --max-tool-output-chars 4000 \
  --recent-tail-messages 12
```

Dry-run:

```bash
python scripts/smoke_compact.py \
  --hermes-plaintext-fixture tests/fixtures/private/hermes-plaintext-real.compact.json \
  --dry-run
```

Execute:

```bash
python scripts/smoke_compact.py \
  --auth-mode codex_oauth \
  --hermes-plaintext-fixture tests/fixtures/private/hermes-plaintext-real.compact.json \
  --execute
```

**Record only safe results:**

- HTTP class/status
- whether endpoint accepted payload
- whether output was plaintext readable or opaque compaction
- item counts / char counts
- exception class/category
- no raw request/response content

**Commit policy:**

- Do not commit private fixture or output.
- If smoke reveals a code bug, write a failing public synthetic test, fix it, commit/push the code only.
- If smoke only reveals product behavior, document safe metrics in README or plan update without private content.

## Task 5: Documentation and Result Framing

**Objective:** Make it hard for future readers to overstate the result.

**Files:**

- Modify: `README.md`
- Possibly modify: `.hermes/plans/2026-05-01-codex-remote-native-parity.md` only to link this follow-up plan, if desired after implementation

**Docs should say:**

- Hermes JSONL conversion is a lossy plaintext experiment.
- It does not reconstruct Codex-native encrypted state.
- Passing this smoke means `/responses/compact` accepts Hermes-derived plaintext history.
- Failing this smoke does not prove Codex compact is bad; it may require native encrypted Codex rollout state.
- Runtime adoption still requires separate quality evaluation against the built-in compressor.

**Verification:**

```bash
python -m pytest -q
```

**Commit:**

```bash
git add README.md .hermes/plans/2026-05-01_140037-hermes-jsonl-to-codex-plaintext-compact.md
git commit -m "docs: plan hermes plaintext compact compatibility"
```

## Risks and Tradeoffs

### Risk: False negative

If plaintext-only compact fails, that may only mean `/responses/compact` expects Codex-native encrypted state for this auth/backend path. It does not prove Codex compact quality is poor.

### Risk: False optimism

If plaintext-only compact succeeds and returns readable text, the output may still be worse than built-in Hermes compression because it lacks native reasoning/checkpoint state and exact Codex tool semantics.

### Risk: Privacy leakage

Hermes JSONL can contain Slack messages, filesystem paths, command output, Gmail snippets, credentials, or private repo details. Keep raw fixtures ignored, print metrics only, and preserve the existing redaction discipline.

### Risk: Tool-pair corruption

The most dangerous conversion bug is mismatching `function_call` / `function_call_output`. Tests should fail hard on orphan outputs and duplicate call IDs unless existing converter semantics already handle them safely.

### Risk: Scope creep

Do not start improving local-style summaries or runtime compression based on this experiment. This plan only answers whether Hermes JSONL can be converted into a plaintext compact request and whether the endpoint accepts it.

## Open Questions

1. Does `/responses/compact` accept plaintext-only `input` with no encrypted reasoning/compaction items under `codex_oauth`?
2. If accepted, does it return readable output or only opaque `type: compaction`?
3. Are Codex identity headers helpful or irrelevant for plaintext-only input?
4. How much tool output should be retained before endpoint acceptance or quality degrades?
5. Does `focus_topic` materially change output once it is correctly included in `instructions`?

## Recommended Implementation Order

1. Add strict plaintext fixture loader.
2. Add JSONL → plaintext fixture converter with TDD.
3. Add smoke support and safe dry-run metrics.
4. Run one private real-session dry-run.
5. Run one private real-session execute smoke.
6. Document safe result and decide whether quality evaluation is worth a separate plan.
