# Codex-equivalent Compact Pipeline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the current flattened compact input with a Codex-like pipeline: Hermes messages → OpenAI/Codex Responses `ResponseItem[]` → Codex-equivalent remote compact payload/preprocessing → filtered replacement history → valid Hermes OpenAI-format messages.

**Architecture:** Add a narrow conversion layer and preprocessing layer inside the standalone `hermes-codex-compact` plugin. Keep Hermes core unchanged and keep production `context.engine` unchanged during development. Build this through fixture-based TDD, then re-run the real-session A/B smoke against Hermes built-in compression.

**Tech Stack:** Python 3.11, pytest, Hermes standalone plugin API, OpenAI/Codex Responses compact endpoint, existing Hermes `agent.codex_responses_adapter` behavior as reference, Codex Rust implementation as algorithm reference.

---

## Context and source-of-truth references

### Repo

```text
/Users/ryo.nakae/.hermes/plugins/hermes-codex-compact
```

### Current state

The plugin can already:

- load JSONL fixtures from `tests/fixtures/private/` without committing real sessions;
- call Codex OAuth `/responses/compact` against a real Hermes session;
- run Hermes built-in compressor against the same fixture;
- compare rough replacement sizes.

Real-session smoke result:

```text
original: 107 messages, ~201K content chars
current codex_compact: ~95K replacement chars, mostly raw flattened history
Hermes built-in: ~33K replacement chars, structured checkpoint summary
```

Conclusion: API reachability is proven, but the compact input representation is wrong.

### Hermes references

```text
~/.hermes/hermes-agent/agent/context_engine.py
~/.hermes/hermes-agent/agent/context_compressor.py
~/.hermes/hermes-agent/agent/codex_responses_adapter.py
~/.hermes/hermes-agent/run_agent.py
```

Important Hermes behavior:

- `ContextEngine.compress(messages)` receives and returns OpenAI chat-format Hermes messages.
- Hermes built-in compressor prunes old tool results, protects head/tail, summarizes middle turns, then sanitizes tool pairs.
- `agent.codex_responses_adapter._chat_messages_to_responses_input()` already converts Hermes chat-style messages to Responses input items for Codex Responses turns.

### Codex references

```text
/tmp/openai-codex/codex-rs/core/src/tasks/compact.rs
/tmp/openai-codex/codex-rs/core/src/compact_remote.rs
/tmp/openai-codex/codex-rs/core/src/compact.rs
/tmp/openai-codex/codex-rs/core/src/client.rs
/tmp/openai-codex/codex-rs/core/src/client_common.rs
/tmp/openai-codex/codex-rs/protocol/src/models.rs
```

Important Codex remote compact behavior:

1. `history = sess.clone_history()`
2. `base_instructions = sess.get_base_instructions()`
3. `trim_function_call_history_to_fit_context_window(...)`
4. `prompt_input = history.for_prompt(input_modalities)`
5. `tools = built_tools(...).model_visible_specs()`
6. Build `Prompt { input, tools, parallel_tool_calls, base_instructions, personality, output_schema: None, output_schema_strict: true }`
7. `compact_conversation_history()` sends payload:

```json
{
  "model": "...",
  "input": [ResponseItem...],
  "instructions": "<base instructions>",
  "tools": [...],
  "parallel_tool_calls": true,
  "reasoning": {...},
  "text": {...}
}
```

8. Compact response is `ResponseItem[]`.
9. `process_compacted_history()` drops developer/stale prefix/non-real-user items.
10. Mid-turn compaction may reinject initial context before the last real user/summary. Manual/pre-turn compaction does not.

---

## Non-goals for this phase

- Do not switch runtime config to `context.engine: codex_compact`.
- Do not edit Hermes core.
- Do not implement durable checkpoint DB or retrieval tools.
- Do not read `~/.hermes/auth.json` or `~/.codex/auth.json` directly.
- Do not store real session fixtures, raw compact payloads, raw responses, or API secrets in git.
- Do not chase perfect Codex parity for every `ResponseItem` variant in the first implementation; support the variants Hermes can actually produce first.

---

## Target file layout

Create/modify:

```text
responses_conversion.py          # Hermes chat messages <-> Codex-like ResponseItem dicts
compact_preprocess.py            # Codex-equivalent compact preprocessing/postprocessing
conversion.py                    # Delegate payload construction to new layers
engine.py                        # Use new pipeline in compress()
scripts/smoke_compact.py         # Add debug summaries for new payload shape
scripts/compare_builtin_fixture.py
README.md
AGENTS.md
.hermes/plans/2026-04-30-codex-equivalent-compact-pipeline.md
```

Tests:

```text
tests/test_responses_conversion.py
tests/test_compact_preprocess.py
tests/test_engine_codex_pipeline.py
tests/test_smoke_fixture.py       # extend existing
```

---

## Design details

### ResponseItem wire shapes to support first

Use Python dicts matching Codex/OpenAI wire shape, not Rust classes.

#### User message

```python
{
    "type": "message",
    "role": "user",
    "content": [{"type": "input_text", "text": "..."}],
}
```

#### Assistant message

```python
{
    "type": "message",
    "role": "assistant",
    "content": [{"type": "output_text", "text": "..."}],
}
```

#### Assistant function call

```python
{
    "type": "function_call",
    "call_id": "call_...",
    "name": "terminal",
    "arguments": "{...}",
}
```

#### Tool/function output

```python
{
    "type": "function_call_output",
    "call_id": "call_...",
    "output": "...",
}
```

#### Optional reasoning replay

Only preserve if Hermes message contains `codex_reasoning_items` with `encrypted_content`:

```python
{
    "type": "reasoning",
    "encrypted_content": "...",
    "summary": [...],
}
```

Do not include server-side `id` in replayed reasoning items.

### Conversion policy

- `system` / `developer` chat messages do not become `input` items by default.
- System/developer text becomes compact `instructions`, joined with clear separators.
- Multimodal text parts convert to `input_text` or `output_text` according to role.
- Images/files become safe placeholders unless a valid Responses image part is intentionally supported later.
- Assistant `tool_calls` become separate `function_call` items after any assistant visible text item.
- Tool result messages become `function_call_output` items.
- Missing/unstable call ids use deterministic ids based on function name, arguments, and local index.
- Dangling tool calls / orphan tool results are removed before payload construction.

### Preprocessing policy

Codex remote compact trims generated tail items only if the compact request does not fit the context window. Hermes does not have Codex `ContextManager`, so implement a conservative approximation:

1. Estimate visible chars/tokens for each ResponseItem.
2. If under budget, do not trim.
3. If over budget, remove old/large generated items first:
   - old `function_call_output` items;
   - old `function_call` items whose output is also removed;
   - old assistant messages with no user-visible value;
   - never remove the latest real user message;
   - never leave orphan `function_call_output` or dangling `function_call`.
4. Prefer truncating very large tool outputs over deleting latest user context.
5. Record preprocessing stats for smoke/debug summaries.

### Payload policy

New payload builder should produce:

```python
{
    "model": config.model,
    "input": response_items,
    "instructions": base_instructions,
    "tools": responses_tools,
    "parallel_tool_calls": config.parallel_tool_calls,
    # include only when configured / meaningful
    "reasoning": {...},
    "text": {...},
}
```

For fixture smoke, tools default to `[]` because active Hermes tool schemas are not available from exported history. Add a hook for optional provided schemas later.

### Postprocessing policy

Compact response may be:

- `{"output": [ResponseItem...]}`
- `{"output_text": "..."}`
- other Responses-like content lists

Postprocessing should:

1. Prefer structured `output` item list when present.
2. Filter like Codex `should_keep_compacted_history_item()`:
   - drop developer messages;
   - keep assistant messages;
   - keep real user messages;
   - keep compaction/summary user messages;
   - drop function calls/results unless we decide to preserve them later.
3. If only text exists, wrap it as a summary user message using existing checkpoint prefix.
4. Convert filtered ResponseItems back to valid Hermes chat messages.
5. Append safe recent tail from original Hermes messages if structured compact output lacks latest user intent.
6. Run existing `sanitize_tail_tool_pairs()` before returning.

---

## Task plan

### Task 1: Add failing tests for Hermes chat → ResponseItem conversion

**Objective:** Define the expected wire shape for user, assistant, tool call, and tool output conversion.

**Files:**

- Create: `tests/test_responses_conversion.py`
- Create later: `responses_conversion.py`

**Step 1: Write failing tests**

Add tests:

```python
from responses_conversion import hermes_messages_to_response_items


def test_user_and_assistant_messages_become_response_message_items():
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    items, instructions = hermes_messages_to_response_items(messages)

    assert instructions == "rules"
    assert items == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]},
    ]


def test_assistant_tool_call_and_tool_result_become_function_items():
    messages = [
        {
            "role": "assistant",
            "content": "I will run it",
            "tool_calls": [{
                "id": "call_123",
                "type": "function",
                "function": {"name": "terminal", "arguments": "{\"command\": \"pwd\"}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_123", "name": "terminal", "content": "ok"},
    ]

    items, instructions = hermes_messages_to_response_items(messages)

    assert instructions == ""
    assert items[0]["type"] == "message"
    assert items[1] == {
        "type": "function_call",
        "call_id": "call_123",
        "name": "terminal",
        "arguments": "{\"command\": \"pwd\"}",
    }
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "call_123",
        "output": "ok",
    }
```

**Step 2: Verify RED**

Run:

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: FAIL because `responses_conversion` does not exist.

**Step 3: Implement minimal `responses_conversion.py`**

Create functions:

```python
def hermes_messages_to_response_items(messages, *, max_tool_output_chars=None): ...
def content_to_response_content_parts(content, *, role): ...
def deterministic_call_id(name, arguments, index): ...
```

Implementation can initially support only string content and basic tool calls.

**Step 4: Verify GREEN**

Run:

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: PASS.

---

### Task 2: Add conversion tests for multimodal/list content and deterministic ids

**Objective:** Match Hermes `codex_responses_adapter` behavior for content parts and missing call ids.

**Files:**

- Modify: `tests/test_responses_conversion.py`
- Modify: `responses_conversion.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_list_content_uses_role_specific_text_part_types():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "u"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
    ]

    items, _ = hermes_messages_to_response_items(messages)

    assert items[0]["content"] == [{"type": "input_text", "text": "u"}]
    assert items[1]["content"] == [{"type": "output_text", "text": "a"}]


def test_missing_tool_call_id_is_deterministic_and_output_uses_same_id():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "terminal", "arguments": "{}"}}]},
    ]

    first, _ = hermes_messages_to_response_items(messages)
    second, _ = hermes_messages_to_response_items(messages)

    assert first[0]["type"] == "function_call"
    assert first[0]["call_id"].startswith("call_")
    assert first == second
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: FAIL on list content / deterministic id support.

**Step 3: Implement**

- Convert text/input_text/output_text parts by role.
- Replace unsupported image/file/audio parts with short placeholder text.
- Generate stable `call_<sha256[:12]>` ids.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: PASS.

---

### Task 3: Add tool-pair sanitization for ResponseItems

**Objective:** Ensure payload never contains dangling `function_call` or orphan `function_call_output`.

**Files:**

- Modify: `tests/test_responses_conversion.py`
- Modify: `responses_conversion.py`

**Step 1: Write failing tests**

```python
def test_orphan_function_call_output_is_removed():
    messages = [{"role": "tool", "tool_call_id": "call_missing", "content": "orphan"}]

    items, _ = hermes_messages_to_response_items(messages)

    assert items == []


def test_dangling_function_call_without_output_is_removed_when_requested():
    messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}]}]

    items, _ = hermes_messages_to_response_items(messages, drop_incomplete_tool_pairs=True)

    assert items == []
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: FAIL.

**Step 3: Implement**

Add:

```python
def sanitize_response_tool_pairs(items): ...
```

Rules:

- keep `function_call` only if matching output exists when `drop_incomplete_tool_pairs=True`;
- keep `function_call_output` only if matching call exists;
- preserve surrounding messages.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_responses_conversion.py -q
```

Expected: PASS.

---

### Task 4: Build Codex-like compact payload builder

**Objective:** Replace flattened `hermes_messages_to_compact_payload()` with a Codex-like payload builder while preserving old tests via compatibility fields if needed.

**Files:**

- Modify: `tests/test_conversion.py`
- Create: `tests/test_compact_preprocess.py`
- Modify: `conversion.py`
- Create: `compact_preprocess.py`

**Step 1: Write failing tests**

```python
from compact_preprocess import build_codex_compact_payload


def test_payload_uses_response_items_and_base_instructions():
    messages = [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "hello"},
    ]

    payload, stats = build_codex_compact_payload(messages, model="gpt-5.5")

    assert payload["model"] == "gpt-5.5"
    assert payload["instructions"] == "system rules"
    assert payload["input"][0]["type"] == "message"
    assert payload["tools"] == []
    assert payload["parallel_tool_calls"] is False
    assert stats["original_messages"] == 2
    assert stats["input_items"] == 1
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_compact_preprocess.py -q
```

Expected: FAIL because `compact_preprocess` does not exist.

**Step 3: Implement minimal builder**

Create:

```python
def build_codex_compact_payload(messages, *, model, tools=None, parallel_tool_calls=False, reasoning=None, text=None, max_tool_output_chars=None, token_budget=None): ...
```

Use `hermes_messages_to_response_items()` internally.

**Step 4: Update `conversion.py`**

Either:

- make `hermes_messages_to_compact_payload()` call `build_codex_compact_payload()`; or
- keep old function but add `mode="responses_items"` default.

Prefer one path to avoid split logic.

**Step 5: Verify GREEN**

```bash
python -m pytest tests/test_compact_preprocess.py tests/test_conversion.py -q
```

Expected: PASS.

---

### Task 5: Add conservative context-window preprocessing

**Objective:** Approximate Codex `trim_function_call_history_to_fit_context_window()` in plugin-safe Python.

**Files:**

- Modify: `tests/test_compact_preprocess.py`
- Modify: `compact_preprocess.py`

**Step 1: Write failing tests**

```python
def test_preprocess_truncates_old_large_tool_outputs_before_latest_user():
    messages = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}], "content": ""},
        {"role": "tool", "tool_call_id": "call_1", "content": "x" * 10_000},
        {"role": "user", "content": "latest request must remain"},
    ]

    payload, stats = build_codex_compact_payload(
        messages,
        model="gpt-5.5",
        token_budget=1000,
        max_tool_output_chars=100,
    )

    serialized = str(payload["input"])
    assert "latest request must remain" in serialized
    assert "truncated" in serialized
    assert stats["truncated_tool_outputs"] == 1
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_compact_preprocess.py -q
```

Expected: FAIL.

**Step 3: Implement**

Add helpers:

```python
def estimate_response_item_visible_chars(item): ...
def truncate_function_outputs(items, max_chars): ...
def trim_response_items_to_budget(items, budget_chars, *, preserve_latest_user=True): ...
```

Keep this deliberately conservative:

- truncate large outputs first;
- if still too large, remove oldest complete tool call/output pairs;
- do not delete latest real user item;
- sanitize tool pairs after trimming.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_compact_preprocess.py -q
```

Expected: PASS.

---

### Task 6: Convert compact response `ResponseItem[]` back to Hermes messages

**Objective:** Prefer structured compact output over `output_text`, then return valid Hermes message history.

**Files:**

- Create: `tests/test_compact_postprocess.py`
- Modify: `compact_preprocess.py` or create `compact_postprocess.py`
- Modify: `engine.py`

**Step 1: Write failing tests**

```python
from compact_postprocess import compact_response_to_hermes_messages


def test_structured_output_messages_convert_to_hermes_messages():
    response = {
        "output": [
            {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "stale dev"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "summary"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "ok"}]},
        ]
    }

    messages = compact_response_to_hermes_messages(response, original_messages=[])

    assert messages == [
        {"role": "user", "content": "summary"},
        {"role": "assistant", "content": "ok"},
    ]


def test_output_text_fallback_wraps_checkpoint_message():
    response = {"output_text": "Goal and next steps"}

    messages = compact_response_to_hermes_messages(response, original_messages=[])

    assert messages[0]["role"] == "user"
    assert "Context compacted by hermes-codex-compact" in messages[0]["content"]
    assert "Goal and next steps" in messages[0]["content"]
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_compact_postprocess.py -q
```

Expected: FAIL.

**Step 3: Implement**

Add:

```python
def compact_response_to_hermes_messages(response, original_messages, *, recent_tail_messages=0): ...
def response_item_to_hermes_message(item): ...
def should_keep_compacted_response_item(item): ...
```

Codex-like filter:

- drop developer messages;
- keep assistant messages;
- keep user messages that are not obvious stale instruction wrappers;
- drop function calls/results initially;
- fallback to checkpoint wrapper when only text exists.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_compact_postprocess.py -q
```

Expected: PASS.

---

### Task 7: Integrate new pipeline into `CodexCompactEngine.compress()`

**Objective:** Make engine use Codex-like payload construction and structured postprocessing.

**Files:**

- Modify: `engine.py`
- Modify: `tests/test_engine.py` or create `tests/test_engine_codex_pipeline.py`

**Step 1: Write failing test**

```python
from engine import CodexCompactEngine


class FakeClient:
    def __init__(self):
        self.payloads = []

    def compact(self, payload):
        self.payloads.append(payload)
        return {
            "output": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "compact summary"}]}
            ]
        }


def test_engine_uses_codex_like_payload_and_structured_response():
    client = FakeClient()
    engine = CodexCompactEngine(client=client, recent_tail_messages=0)

    result = engine.compress([
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"},
    ])

    assert client.payloads[0]["instructions"] == "rules"
    assert client.payloads[0]["input"][0]["type"] == "message"
    assert result == [{"role": "user", "content": "compact summary"}]
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_engine_codex_pipeline.py -q
```

Expected: FAIL until engine uses new pipeline.

**Step 3: Implement**

In `engine.compress()`:

- call `build_codex_compact_payload(...)`;
- call client;
- call `compact_response_to_hermes_messages(...)`;
- run existing `sanitize_tail_tool_pairs()`;
- fail closed by returning original messages on exception.

Preserve `last_error` behavior.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_engine_codex_pipeline.py tests/test_engine.py -q
```

Expected: PASS.

---

### Task 8: Update smoke script summaries for the new payload shape

**Objective:** Make real-session smoke show whether the new conversion is actually structural.

**Files:**

- Modify: `scripts/smoke_compact.py`
- Modify: `tests/test_smoke_fixture.py`

**Step 1: Write failing test**

```python
def test_dry_run_summary_reports_response_item_types():
    fixture = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"
    payload, messages = build_payload_from_fixture(fixture, model="gpt-test", focus_topic=None)
    summary = dry_run_summary(payload, messages, fixture=fixture, compare_builtin=False)

    assert "response_item_types" in summary["payload_summary"]
    assert summary["payload_summary"]["response_item_types"]["message"] >= 1
```

**Step 2: Verify RED**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

Expected: FAIL.

**Step 3: Implement**

Add payload stats:

- item type counts;
- total visible chars;
- function_call count;
- function_call_output count;
- truncated output count from preprocessing stats if available;
- instructions chars;
- tools count.

**Step 4: Verify GREEN**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

Expected: PASS.

---

### Task 9: Re-run real-session A/B smoke

**Objective:** Measure whether new pipeline improves over flattened payload.

**Files:**

- No committed real-session fixture changes.
- Private outputs under `tests/fixtures/private/` only.

**Step 1: Confirm private fixture is ignored**

Run:

```bash
git check-ignore -v tests/fixtures/private/context-compression-real.jsonl
```

Expected:

```text
.gitignore:...:tests/fixtures/private/ tests/fixtures/private/context-compression-real.jsonl
```

**Step 2: Dry-run new payload**

Run:

```bash
python scripts/smoke_compact.py \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --model gpt-5.5 \
  --compare-builtin \
  > tests/fixtures/private/context-compression-new-dry-run.json
```

Expected:

- JSON file created under ignored private dir;
- payload summary includes ResponseItem types;
- no raw secrets in stdout.

**Step 3: Execute Codex compact**

Run:

```bash
python scripts/smoke_compact.py \
  --auth-mode codex_oauth \
  --model gpt-5.5 \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --focus-topic 'Hermes ContextEngine plugin real-session compression test' \
  --execute \
  > tests/fixtures/private/context-compression-codex-responseitems-result.json
```

Expected:

- exit code 0;
- replacement history produced;
- output remains ignored.

**Step 4: Compare with built-in**

Run:

```bash
python scripts/compare_builtin_fixture.py \
  tests/fixtures/private/context-compression-real.jsonl \
  --model gpt-5.5 \
  --focus-topic 'Hermes ContextEngine plugin real-session compression test' \
  > tests/fixtures/private/context-compression-builtin-result-v2.json
```

Then run a small local analyzer:

```bash
python - <<'PY'
import json
from pathlib import Path
root = Path('tests/fixtures/private')
for name in [
    'context-compression-codex-responseitems-result.json',
    'context-compression-builtin-result-v2.json',
]:
    data = json.loads((root / name).read_text())
    repl = data['replacement']
    original = data['message_summary']['content_chars']
    chars = sum(len(m.get('content') or '') if isinstance(m.get('content'), str) else len(str(m.get('content'))) for m in repl)
    print(name, 'messages=', len(repl), 'chars=', chars, 'ratio=', round(chars / original, 3))
PY
```

Acceptance target for this phase:

- Codex compact output no longer preserves raw `skill_view` / huge tool output verbatim;
- replacement ratio should be materially below previous 0.47;
- ideal target is <= 0.25, but do not fake quality to hit ratio;
- latest user intent and next steps must survive.

---

### Task 10: Update docs and plan with measured result

**Objective:** Keep future agents from repeating the flattened-history mistake.

**Files:**

- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.hermes/plans/2026-04-30-codex-equivalent-compact-pipeline.md`

**Step 1: Update README**

Add a short section:

```markdown
## Codex-like conversion pipeline

The compact endpoint expects Responses-style `ResponseItem[]`, not flattened chat text. The plugin converts Hermes chat messages into Codex-like response items before calling `/responses/compact`.
```

Include smoke commands.

**Step 2: Update AGENTS.md**

Add:

- start with `responses_conversion.py` and `compact_preprocess.py`;
- never reintroduce flattened tool-output payloads as default;
- private fixture outputs remain ignored.

**Step 3: Verify docs mention private fixture safety**

Run:

```bash
grep -n "tests/fixtures/private" README.md AGENTS.md .gitignore
```

Expected: all three mention private fixture handling.

---

### Task 11: Full verification before commit

**Objective:** Ensure tests, syntax, ignored private data, and plugin discovery are clean.

**Files:** all changed files.

**Step 1: Run unit tests**

```bash
python -m pytest -q
```

Expected:

```text
all tests passed; private real-session test skipped unless opt-in
```

**Step 2: Run py_compile**

```bash
python -m py_compile \
  __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py \
  responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py \
  scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py \
  tests/*.py
```

Expected: exit code 0.

**Step 3: Confirm private data is ignored**

```bash
git status --short --ignored tests/fixtures/private
git diff --cached --name-only | grep 'tests/fixtures/private' && exit 2 || true
```

Expected:

```text
!! tests/fixtures/private/
```

and no staged private files.

**Step 4: Plugin discovery**

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

---

## Commit sequence

Use small commits if implementing manually:

1. `test: define responses item conversion behavior`
2. `feat: convert Hermes messages to response items`
3. `feat: build codex-like compact payloads`
4. `feat: postprocess compact response items`
5. `feat: route compact engine through response item pipeline`
6. `docs: document codex-like compact pipeline`

If implementing in one focused session, a single commit is acceptable after all tests pass:

```bash
git add -A
git commit -m "feat: use codex-like response items for compact payloads"
git push
```

Before committing, always confirm:

```bash
git diff --cached --name-only | grep 'tests/fixtures/private' && exit 2 || true
```

---

## Acceptance criteria

The phase is complete when:

- `responses_conversion.py` converts Hermes messages to Codex-like `ResponseItem` dicts.
- Compact payload uses structured `ResponseItem[]`, base instructions, tools field, and `parallel_tool_calls`.
- Engine prefers structured compact response output over text flattening.
- Real-session smoke runs against ignored private fixture.
- Built-in comparison still runs.
- New Codex compact output is materially less raw-history-like than previous result.
- README/AGENTS explain the new pipeline and private fixture safety.
- `python -m pytest -q` and py_compile pass.
- Plugin discovery reports `found=True`, `enabled=True`, `error=None`.
- No real session fixture or compact result JSON is staged or committed.

---

## Open questions for later phases

- Can we access active Hermes tool schemas inside live `ContextEngine.compress()` without relying on private `AIAgent` state?
- Should `ContextEngine.compress()` accept richer metadata in Hermes core later, or should the plugin infer everything from messages/config?
- Should remote compact fall back to Hermes built-in compressor automatically on poor compression ratio?
- Can `responses/compact` official OpenAI API key mode produce better output than Codex OAuth for Hermes histories?
- Should we preserve compact response `function_call` / `function_call_output` items, or always collapse them into text before returning Hermes messages?
