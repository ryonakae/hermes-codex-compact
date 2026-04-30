# Codex Compact Parity Improvements Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Improve `hermes-codex-compact` quality by making its conversion, compact payload, and preprocessing behavior closer to what OpenAI Codex actually sends to `/responses/compact`, before adding any built-in fallback or custom handoff post-pass.

**Architecture:** Keep the plugin standalone and keep `context.engine` unchanged in production. Add Codex-parity modes behind explicit config/options, compare them against the current structured pipeline with private real-session fixtures, and commit in small verified milestones. The work focuses on replay fidelity first, then payload fidelity, then preprocessing fidelity.

**Tech Stack:** Python 3.11, pytest, Hermes standalone ContextEngine plugin, OpenAI/Codex Responses `ResponseItem` wire shapes, Codex Rust reference implementation.

---

## Source-of-truth references

### Plugin repo

```text
/Users/ryo.nakae/.hermes/plugins/hermes-codex-compact
```

### Plugin files to modify

```text
responses_conversion.py
compact_preprocess.py
compact_postprocess.py
engine.py
config.py
scripts/smoke_compact.py
README.md
AGENTS.md
tests/test_responses_conversion.py
tests/test_compact_preprocess.py
tests/test_engine_codex_pipeline.py
tests/test_smoke_fixture.py
```

### Reference implementations

```text
/Users/ryo.nakae/.hermes/hermes-agent/agent/codex_responses_adapter.py
/tmp/openai-codex/codex-rs/core/src/compact_remote.rs
/tmp/openai-codex/codex-rs/core/src/client.rs
/tmp/openai-codex/codex-rs/core/src/client_common.rs
/tmp/openai-codex/codex-rs/core/src/compact.rs
/tmp/openai-codex/codex-rs/protocol/src/models.rs
```

### Key Codex behavior to mirror

Remote compact path:

```text
sess.clone_history()
→ sess.get_base_instructions()
→ trim_function_call_history_to_fit_context_window() only if needed
→ history.for_prompt(input_modalities)
→ built_tools(...).model_visible_specs()
→ Prompt { input, tools, parallel_tool_calls, base_instructions, personality, output_schema: None }
→ compact_conversation_history()
→ /responses/compact payload
→ process_compacted_history()
```

Payload shape:

```json
{
  "model": "...",
  "input": ["ResponseItem..."],
  "instructions": "<base instructions only>",
  "tools": ["model-visible tool specs"],
  "parallel_tool_calls": true,
  "reasoning": {"effort": "...", "summary": "..."},
  "text": {"verbosity": "..."}
}
```

---

## Non-goals for this phase

- Do not switch runtime config to `context.engine: codex_compact`.
- Do not add built-in compressor fallback yet.
- Do not implement a custom Hermes handoff summary post-pass yet.
- Do not edit Hermes core.
- Do not commit private fixtures, raw payloads, raw responses, tokens, OAuth credentials, or API keys.
- Do not direct-read `~/.hermes/auth.json` or `~/.codex/auth.json`.
- Do not make flattened tool-output payloads the default again.

---

## Acceptance criteria

- Tests pass:

```bash
python -m pytest -q
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py tests/*.py
```

- Plugin discovery remains clean:

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

- Private fixture files remain ignored:

```bash
git status --short --ignored
```

Expected includes only ignored private/runtime artifacts such as:

```text
!! tests/fixtures/private/
```

- Smoke comparison can run these variants without changing production config:

```text
current structured pipeline
conversion parity
conversion + payload parity
conversion + payload + preprocessing parity
```

---

## Commit strategy

Use small commits and push each stable milestone.

Suggested commit sequence:

```text
feat: improve codex response replay parity
feat: add codex compact prompt parity mode
feat: mirror codex tool-pair preprocessing
feat: compare codex compact parity variants
```

Do not bundle docs-only plan edits with code unless the docs describe that exact milestone.

---

# Phase 1: Response replay / conversion parity

## Task 1: Add tool id split tests

**Objective:** Define Hermes core-compatible handling for `call_id|fc_id` and `fc_`-only tool IDs.

**Files:**

- Modify: `tests/test_responses_conversion.py`
- Modify later: `responses_conversion.py`

**Step 1: Write failing tests**

Add tests covering:

```python
def test_tool_call_id_pair_is_split_for_function_call_and_output():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_pair123|fc_pair123",
                "function": {"name": "terminal", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_pair123|fc_pair123", "content": "ok"},
    ]

    items, _ = hermes_messages_to_response_items(messages, drop_incomplete_tool_pairs=False)

    assert items[0]["call_id"] == "call_pair123"
    assert items[1]["call_id"] == "call_pair123"


def test_fc_only_tool_id_derives_call_id():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "fc_abc123",
                "function": {"name": "terminal", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_abc123", "content": "ok"},
    ]

    items, _ = hermes_messages_to_response_items(messages, drop_incomplete_tool_pairs=False)

    assert items[0]["call_id"] == "call_abc123"
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: FAIL on current ID handling.

**Step 3: Implement helpers**

Add to `responses_conversion.py`:

```python
def split_responses_tool_id(raw_id: Any) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(raw_id, str):
        return None, None
    value = raw_id.strip()
    if not value:
        return None, None
    if "|" in value:
        call_id, response_item_id = value.split("|", 1)
        return call_id.strip() or None, response_item_id.strip() or None
    if value.startswith("fc_"):
        return None, value
    return value, None


def call_id_from_response_item_id(response_item_id: Optional[str]) -> Optional[str]:
    if isinstance(response_item_id, str) and response_item_id.startswith("fc_"):
        suffix = response_item_id[len("fc_"):]
        if suffix:
            return f"call_{suffix}"
    return None
```

Update assistant tool call and tool result conversion to use these helpers before falling back to deterministic IDs.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: PASS.

**Step 5: Commit**

Commit later with all Phase 1 changes unless this task becomes large.

---

## Task 2: Add `codex_message_items` exact replay tests

**Objective:** Preserve assistant replay items with `id`, `phase`, `status`, and normalized `output_text`, matching Hermes core behavior.

**Files:**

- Modify: `tests/test_responses_conversion.py`
- Modify later: `responses_conversion.py`

**Step 1: Write failing tests**

Add:

```python
def test_codex_message_items_are_replayed_before_reconstructed_content():
    messages = [{
        "role": "assistant",
        "content": "fallback should not duplicate",
        "codex_message_items": [{
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "phase": "final_answer",
            "content": [{"type": "text", "text": "exact replay"}],
        }],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert items == [{
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "phase": "final_answer",
        "content": [{"type": "output_text", "text": "exact replay"}],
    }]
```

Add invalid replay fallback:

```python
def test_invalid_codex_message_items_fall_back_to_assistant_content():
    messages = [{
        "role": "assistant",
        "content": "fallback",
        "codex_message_items": [{"type": "message", "role": "user", "content": []}],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert items[0]["role"] == "assistant"
    assert "fallback" in str(items[0]["content"])
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: FAIL because plugin currently ignores `codex_message_items`.

**Step 3: Implement replay**

Add helper:

```python
def replay_codex_message_items(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    ...
```

Rules:

- Only accept `type == "message"` and `role == "assistant"`.
- Require list content.
- Preserve `id` when non-empty.
- Preserve `phase` when non-empty.
- Normalize `status` to `completed`, `incomplete`, or `in_progress`; default `completed`.
- Normalize `text` / `output_text` parts to `output_text`.
- If any replay item is emitted, do not reconstruct assistant text from `content`.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: PASS.

---

## Task 3: Match reasoning replay behavior

**Objective:** Make reasoning item replay assistant-only, globally deduplicated, and safe for reasoning-only assistant turns.

**Files:**

- Modify: `tests/test_responses_conversion.py`
- Modify: `responses_conversion.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_reasoning_replay_is_assistant_only():
    messages = [{
        "role": "user",
        "content": "hello",
        "codex_reasoning_items": [{"id": "r1", "type": "reasoning", "encrypted_content": "secret"}],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert all(item.get("type") != "reasoning" for item in items)


def test_reasoning_items_are_deduped_across_messages():
    ri = {"id": "r1", "type": "reasoning", "encrypted_content": "secret", "summary": []}
    messages = [
        {"role": "assistant", "content": "a", "codex_reasoning_items": [ri]},
        {"role": "assistant", "content": "b", "codex_reasoning_items": [ri]},
    ]

    items, _ = hermes_messages_to_response_items(messages)

    assert sum(1 for item in items if item.get("type") == "reasoning") == 1


def test_reasoning_only_assistant_gets_following_empty_message():
    messages = [{
        "role": "assistant",
        "content": "",
        "codex_reasoning_items": [{"id": "r1", "type": "reasoning", "encrypted_content": "secret"}],
    }]

    items, _ = hermes_messages_to_response_items(messages)

    assert items[0]["type"] == "reasoning"
    assert items[1]["role"] == "assistant"
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: FAIL on at least assistant-only or following item behavior.

**Step 3: Implement**

- Move `seen_reasoning_ids` to `hermes_messages_to_response_items()` scope.
- Only call reasoning replay when `role == "assistant"`.
- Strip `id` from outgoing reasoning item, but use it for dedupe.
- Preserve existing fields except unsafe `id` where possible.
- If assistant turn has reasoning but no visible content, replayed message, or tool call, append empty assistant item after reasoning.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: PASS.

---

## Task 4: Add normal vs exact-replay message shape mode

**Objective:** Allow parity smoke to use Hermes core-like `{role, content}` for normal messages while keeping current `type: message` behavior available.

**Files:**

- Modify: `responses_conversion.py`
- Modify: `compact_preprocess.py`
- Modify: `config.py`
- Modify: `tests/test_responses_conversion.py`
- Modify: `tests/test_compact_preprocess.py`

**Step 1: Write failing tests**

Add:

```python
def test_core_like_message_shape_omits_type_for_normal_user_and_assistant():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    items, _ = hermes_messages_to_response_items(messages, message_shape="core")

    assert items == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_response_item_message_shape_remains_supported():
    messages = [{"role": "user", "content": "hello"}]

    items, _ = hermes_messages_to_response_items(messages, message_shape="response_item")

    assert items[0]["type"] == "message"
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_responses_conversion.py tests/test_compact_preprocess.py -q
```

Expected: FAIL because `message_shape` does not exist.

**Step 3: Implement**

Add parameter:

```python
def hermes_messages_to_response_items(..., message_shape: str = "response_item")
```

Allowed values:

```text
response_item  # current behavior
core           # Hermes codex_responses_adapter-like normal message shape
```

For `core` mode:

- String user content: `{"role": "user", "content": "..."}`
- List content: `{"role": "user", "content": [{"type": "input_text", "text": "..."}]}`
- Assistant exact replay from `codex_message_items` still uses `type: "message"`.
- Tool calls/results remain `type: function_call` / `function_call_output`.

Expose config key:

```yaml
codex_compact:
  message_shape: core
```

Default for now can remain `response_item` to avoid changing current tests unexpectedly. Smoke variants should be able to override to `core`.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_responses_conversion.py tests/test_compact_preprocess.py -q
```

Expected: PASS.

**Step 5: Commit and push Phase 1**

```bash
git add responses_conversion.py compact_preprocess.py config.py tests/test_responses_conversion.py tests/test_compact_preprocess.py
git commit -m "feat: improve codex response replay parity"
git push
```

---

# Phase 2: Compact prompt / payload parity

## Task 5: Split base instructions from developer/context input

**Objective:** Stop putting all system/developer messages into `instructions` in parity mode; make `instructions` closer to Codex `base_instructions.text`.

**Files:**

- Modify: `responses_conversion.py`
- Modify: `compact_preprocess.py`
- Modify: `config.py`
- Modify: `tests/test_responses_conversion.py`
- Modify: `tests/test_compact_preprocess.py`

**Step 1: Write failing tests**

Add test:

```python
def test_parity_mode_keeps_developer_context_in_input_and_system_in_instructions():
    messages = [
        {"role": "system", "content": "base rules"},
        {"role": "developer", "content": "repo context"},
        {"role": "user", "content": "do it"},
    ]

    items, instructions = hermes_messages_to_response_items(
        messages,
        message_shape="core",
        instruction_policy="codex_base_only",
    )

    assert instructions == "base rules"
    assert {"role": "developer", "content": "repo context"} in items
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_responses_conversion.py tests/test_compact_preprocess.py -q
```

Expected: FAIL because `instruction_policy` does not exist.

**Step 3: Implement**

Add parameter:

```python
instruction_policy: str = "all_instructions"
```

Policies:

```text
all_instructions       # current behavior: system/developer -> instructions
codex_base_only        # system -> instructions, developer -> input
codex_preserve_prefix  # system/developer -> input except explicit base_system if available later
```

For now implement `codex_base_only`.

Expose config:

```yaml
codex_compact:
  instruction_policy: codex_base_only
```

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_responses_conversion.py tests/test_compact_preprocess.py -q
```

Expected: PASS.

---

## Task 6: Add tool schema conversion and payload injection

**Objective:** Replace hard-coded `tools=[]` in engine parity mode with model-visible tool schemas when available, matching Codex remote compact more closely.

**Files:**

- Modify: `compact_preprocess.py`
- Modify: `engine.py`
- Modify: `tests/test_compact_preprocess.py`
- Modify: `tests/test_engine_codex_pipeline.py`

**Step 1: Write failing tests**

Add conversion test:

```python
def test_chat_tool_schema_converts_to_responses_function_tool():
    tools = [{
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Run shell commands",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
        },
    }]

    converted = responses_tools_from_chat_tools(tools)

    assert converted == [{
        "type": "function",
        "name": "terminal",
        "description": "Run shell commands",
        "strict": False,
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
    }]
```

Add payload test:

```python
def test_payload_includes_responses_tools_and_parallel_flag():
    payload, stats = build_codex_compact_payload(
        [{"role": "user", "content": "hi"}],
        model="gpt-5.5",
        tools=[{"type": "function", "name": "terminal", "parameters": {"type": "object"}, "strict": False}],
        parallel_tool_calls=True,
    )

    assert payload["tools"][0]["name"] == "terminal"
    assert payload["parallel_tool_calls"] is True
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_compact_preprocess.py tests/test_engine_codex_pipeline.py -q
```

Expected: FAIL because helper/runtime injection is missing.

**Step 3: Implement**

- Add `responses_tools_from_chat_tools(tools)` to `compact_preprocess.py`.
- Let `build_codex_compact_payload()` accept either already-Responses tools or chat-completions tools.
- Update `engine.compress()` to prefer tool schemas from config/client injection when available.
- Keep fixture smoke default tools as `[]`, but expose CLI flag or config override later.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_compact_preprocess.py tests/test_engine_codex_pipeline.py -q
```

Expected: PASS.

---

## Task 7: Add reasoning/text controls to payload

**Objective:** Support Codex-like `reasoning` and `text` controls so compact requests can be A/B tested with model-relevant settings.

**Files:**

- Modify: `config.py`
- Modify: `compact_preprocess.py`
- Modify: `tests/test_compact_preprocess.py`
- Modify: `README.md`

**Step 1: Write failing tests**

```python
def test_payload_includes_reasoning_and_text_controls_when_configured():
    payload, _ = build_codex_compact_payload(
        [{"role": "user", "content": "hi"}],
        model="gpt-5.5",
        reasoning={"effort": "medium", "summary": "auto"},
        text={"verbosity": "low"},
    )

    assert payload["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert payload["text"] == {"verbosity": "low"}
```

**Step 2: Verify RED or existing behavior**

```bash
python -m pytest tests/test_compact_preprocess.py -q
```

If this already passes for direct builder calls, add config-loader tests instead.

**Step 3: Implement config fields**

Add to `CodexCompactConfig`:

```python
reasoning_effort: Optional[str]
reasoning_summary: Optional[str]
verbosity: Optional[str]
parallel_tool_calls: bool
```

Build payload controls only when values are present.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_compact_preprocess.py tests/test_auth.py -q
```

Expected: PASS.

**Step 5: Commit and push Phase 2**

```bash
git add config.py compact_preprocess.py engine.py README.md tests/test_compact_preprocess.py tests/test_engine_codex_pipeline.py
git commit -m "feat: add codex compact prompt parity mode"
git push
```

---

# Phase 3: Preprocessing parity

## Task 8: Add Codex-like incomplete tool pair handling

**Objective:** Preserve interrupted tool-call facts by inserting `aborted` output instead of dropping dangling function calls.

**Files:**

- Modify: `responses_conversion.py`
- Modify: `compact_preprocess.py`
- Modify: `tests/test_responses_conversion.py`
- Modify: `tests/test_compact_preprocess.py`

**Step 1: Write failing tests**

```python
def test_missing_tool_output_can_be_synthesized_as_aborted():
    messages = [{
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}],
    }]

    items, _ = hermes_messages_to_response_items(
        messages,
        drop_incomplete_tool_pairs=False,
        missing_tool_output_policy="aborted",
    )

    assert items == [
        {"type": "function_call", "call_id": "call_1", "name": "terminal", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "aborted"},
    ]
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_responses_conversion.py tests/test_compact_preprocess.py -q
```

Expected: FAIL.

**Step 3: Implement**

Add policy:

```text
drop       # current behavior when sanitizing
keep       # preserve calls even if output missing
aborted    # synthesize function_call_output with output="aborted"
```

For Codex parity mode, use `aborted`.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_responses_conversion.py tests/test_compact_preprocess.py -q
```

Expected: PASS.

---

## Task 9: Add Codex parity trimming mode

**Objective:** Avoid pre-truncating tool output in Codex parity smoke unless the compact request exceeds the configured context/budget.

**Files:**

- Modify: `compact_preprocess.py`
- Modify: `config.py`
- Modify: `tests/test_compact_preprocess.py`

**Step 1: Write failing tests**

```python
def test_codex_parity_trimming_keeps_tool_output_when_under_budget():
    output = "x" * 10000
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": output},
    ]

    payload, stats = build_codex_compact_payload(
        messages,
        model="gpt-5.5",
        max_tool_output_chars=4000,
        preprocessing_mode="codex_parity",
        token_budget_chars=20000,
    )

    tool_output = next(item for item in payload["input"] if item.get("type") == "function_call_output")
    assert tool_output["output"] == output
    assert stats["truncated_tool_outputs"] == 0
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_compact_preprocess.py -q
```

Expected: FAIL because current code truncates immediately.

**Step 3: Implement**

Add `preprocessing_mode`:

```text
safe_truncate    # current behavior
codex_parity     # do not truncate unless over budget; trim generated tail first
```

For `codex_parity`:

- If under budget, leave tool output untouched.
- If over budget, remove generated tail items first.
- Do not remove latest real user message.
- Re-run tool-pair sanitization after removal.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_compact_preprocess.py -q
```

Expected: PASS.

**Step 5: Commit and push Phase 3**

```bash
git add responses_conversion.py compact_preprocess.py config.py tests/test_responses_conversion.py tests/test_compact_preprocess.py
git commit -m "feat: mirror codex tool-pair preprocessing"
git push
```

---

# Phase 4: Smoke variants and evaluation

## Task 10: Add smoke variant flags

**Objective:** Compare parity improvements without changing production config.

**Files:**

- Modify: `scripts/smoke_compact.py`
- Modify: `tests/test_smoke_fixture.py`
- Modify: `README.md`

**Step 1: Write failing CLI tests**

Extend existing smoke fixture test to invoke dry-run variants:

```bash
python scripts/smoke_compact.py \
  --fixture tests/fixtures/synthetic_session.jsonl \
  --variant conversion-parity
```

Expected output includes:

```text
variant: conversion-parity
message_shape: core
```

Add variants:

```text
current
conversion-parity
payload-parity
preprocessing-parity
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

Expected: FAIL because `--variant` does not exist.

**Step 3: Implement**

Map variants to config overrides:

```python
current = current defaults
conversion-parity = message_shape=core + replay parity enabled
payload-parity = conversion-parity + instruction_policy=codex_base_only + parallel/tool/reasoning/text settings
preprocessing-parity = payload-parity + missing_tool_output_policy=aborted + preprocessing_mode=codex_parity + recent_tail_messages=0 for smoke
```

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

Expected: PASS.

---

## Task 11: Add deterministic handoff-quality smoke metrics

**Objective:** Measure Codex compact quality without adding fallback or LLM judge.

**Files:**

- Modify: `scripts/smoke_compact.py`
- Modify: `tests/test_smoke_fixture.py`

**Step 1: Write tests**

Add simple metric helper tests for compact output text:

```python
def test_handoff_quality_metrics_detect_key_sections():
    text = """
    ## Active Task
    Implement parity.
    ## Completed Actions
    Added tests.
    ## Remaining Work
    Run smoke.
    commit 1234567
    """

    metrics = evaluate_handoff_quality(text)

    assert metrics["has_active_task"] is True
    assert metrics["has_completed_actions"] is True
    assert metrics["has_remaining_work"] is True
    assert metrics["mentions_commit"] is True
```

Add raw dump detection:

```python
def test_handoff_quality_detects_raw_tool_dump():
    metrics = evaluate_handoff_quality("skill_view output " + "x" * 10000)
    assert metrics["raw_tool_dump_detected"] is True
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

Expected: FAIL because helper does not exist.

**Step 3: Implement**

Metrics:

```text
has_active_task
has_completed_actions
has_remaining_work
has_relevant_files
has_latest_user_direction
mentions_commit
raw_tool_dump_detected
skill_view_dump_detected
likely_resumable
```

Do not use these for fallback yet. Print only.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

Expected: PASS.

---

## Task 12: Run private real-session A/B smoke

**Objective:** Determine whether parity changes improve Codex compact quality on the ignored real session fixture.

**Files:**

- Read only: `tests/fixtures/private/context-compression-real.jsonl`
- Modify if needed: `README.md`, `AGENTS.md`, this plan
- Do not commit: `tests/fixtures/private/*`

**Step 1: Dry-run payload summaries**

```bash
python scripts/smoke_compact.py \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --variant current

python scripts/smoke_compact.py \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --variant conversion-parity

python scripts/smoke_compact.py \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --variant payload-parity

python scripts/smoke_compact.py \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --variant preprocessing-parity
```

Expected: no raw payload/response saved by default.

**Step 2: Execute remote compact intentionally**

Only if credentials are available and the run is intentional:

```bash
python scripts/smoke_compact.py \
  --auth-mode codex_oauth \
  --model gpt-5.5 \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --variant conversion-parity \
  --focus-topic 'Hermes ContextEngine plugin Codex parity compression test' \
  --execute
```

Repeat for payload/preprocessing variants.

**Step 3: Record results safely**

Record only aggregate stats in README/plan:

```text
variant
input item count/type counts
visible chars
replacement messages/chars
quality metrics
notable qualitative result
```

Do not paste private session content.

**Step 4: Verify ignored files**

```bash
git status --short --ignored
```

Expected: private fixture/results remain ignored.

**Step 5: Commit and push smoke/docs**

```bash
git add scripts/smoke_compact.py tests/test_smoke_fixture.py README.md AGENTS.md .hermes/plans/2026-04-30-codex-compact-parity-improvements.md
git commit -m "feat: compare codex compact parity variants"
git push
```

---

## Risks and mitigations

### Risk: Core-like message shape breaks compact endpoint

Mitigation:

- Keep `response_item` message shape available.
- Add smoke variant comparison.
- Do not switch runtime engine.

### Risk: Tool schemas are not available inside `ContextEngine.compress()`

Mitigation:

- Start with explicit injected/minimal schemas for smoke.
- Later investigate Hermes runtime access to active tool schemas.
- Do not block conversion parity on this.

### Risk: Disabling tool truncation increases API cost

Mitigation:

- Only use `codex_parity` mode in smoke/explicit config.
- Print visible chars before execute.
- Keep raw payload dumps disabled by default.

### Risk: `developer` input role is rejected or filtered unexpectedly

Mitigation:

- Add dry-run validation and remote smoke.
- If rejected, use a user-role prefix item such as `[developer context]` only in parity variant and document deviation.

### Risk: Exact Codex parity is impossible without raw `ResponseItem` history

Mitigation:

- Preserve raw `codex_message_items` and `codex_reasoning_items` when present.
- For pure Hermes chat-format fixtures, document unavoidable lossiness.
- Treat full raw ResponseItem storage as a later design topic, not this phase.

---

## Open questions for implementation

1. Can `ContextEngine.compress()` access active Hermes tool schemas cleanly, or do we need config/manual injection first?
2. Does `/responses/compact` accept normal `{role, content}` input items in this endpoint exactly like Responses sampling does?
3. Does developer-role input survive compact endpoint filtering, or should Hermes developer/context be represented differently?
4. Which reasoning/text defaults match `gpt-5.5` Codex behavior best in this environment?
5. Does preserving images as `input_image` create unacceptable privacy/cost issues for Hermes fixtures, or should media omission remain intentional?

---

## Implementation order summary

```text
1. Tool ID split + codex_message_items replay + reasoning replay parity
2. Core-like normal message shape mode
3. Base instructions vs developer/context input separation
4. Tool schema injection + parallel/reasoning/text controls
5. Missing tool output => aborted + Codex parity trimming
6. Smoke variants + deterministic quality metrics
7. Private real-session A/B smoke and docs update
```

The key principle: **before adding custom summary prompting, first make Hermes send compact requests that look much more like actual Codex compact requests.**

---

## 2026-04-30 execution notes

Implemented and pushed the planned milestones:

```text
184a53e feat: improve codex response replay parity
c2d14d8 feat: add codex compact prompt parity mode
07adb6c feat: mirror codex tool-pair preprocessing
acfc00c feat: compare codex compact parity variants
```

Validation after implementation:

```text
73 passed, 1 skipped
py_compile OK
plugin discovery: found=True, enabled=True, error=None
```

Remote Codex OAuth smoke was run against ignored private fixture `tests/fixtures/private/context-compression-real.jsonl` with `gpt-5.5`.

```text
variant                replacement_messages  replacement_chars  likely_resumable
current                3                     2,983              false
conversion-parity      3                     2,983              false
payload-parity         3                     2,983              false
preprocessing-parity   2                     1,234              false
builtin                103                   33,433             n/a
```

Conclusion: the parity work improved request fidelity, but did not improve handoff quality on this Hermes fixture. The compact endpoint appears to return selected response/history items, not the structured checkpoint summary Hermes needs. `preprocessing-parity` was worse than conservative preprocessing. Keep production `context.engine` unchanged.

Recommended next investigation, if continuing:

1. Add an explicit Hermes handoff post-pass after Codex compact output, or
2. Change the input to ask compact to summarize a synthesized task log rather than replay raw history items, or
3. Capture/compare actual Codex `ResponseItem` histories from a native Codex session to determine whether Hermes chat-format export is still too lossy.
