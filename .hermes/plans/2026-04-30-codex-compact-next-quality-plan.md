# Codex Compact Quality Parity Next Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make `hermes-codex-compact` test Codex compaction quality fairly by sending Codex-like compact requests: non-empty base instructions, model-visible tool schemas, correct smoke focus handling, and a separate Codex local-style compaction comparison path.

**Architecture:** Keep the plugin standalone under `~/.hermes/plugins/hermes-codex-compact` and keep production `context.engine` unchanged. Improve request fidelity in small TDD milestones, then compare `/responses/compact` remote compaction against a Codex local-style summary prompt path using ignored private fixtures. Do not add built-in fallback yet; the goal is to understand and improve Codex compact quality, not hide failures.

**Tech Stack:** Python 3.11, pytest, Hermes standalone ContextEngine plugin, OpenAI/Codex Responses payloads, Codex OAuth via Hermes resolver, private JSONL fixtures under `tests/fixtures/private/`.

---

## Context and decisions so far

### What was implemented already

The plugin already has:

- private fixture workflow under `tests/fixtures/private/`;
- synthetic fixture tests;
- Hermes chat messages → Codex-like Responses item conversion;
- `function_call` / `function_call_output` structured tool trajectory conversion;
- `call_id|fc_id` splitting and `fc_...` → `call_...` recovery;
- optional core-like `{role, content}` message shape;
- `instruction_policy`, `parallel_tool_calls`, reasoning/text knobs;
- missing tool-output policy including `aborted`;
- `safe_truncate` vs `codex_parity` preprocessing modes;
- smoke variants: `current`, `conversion-parity`, `payload-parity`, `preprocessing-parity`;
- deterministic handoff quality metrics.

Recent relevant commits:

```text
d00a60c docs: investigate codex compact payload fidelity
26b972e docs: record codex compact remote smoke
acfc00c feat: compare codex compact parity variants
07adb6c feat: mirror codex tool-pair preprocessing
c2d14d8 feat: add codex compact prompt parity mode
184a53e feat: improve codex response replay parity
```

### Remote smoke result

Private fixture:

```text
tests/fixtures/private/context-compression-real.jsonl
```

Fixture summary:

```text
messages=107
roles: user=2, assistant=51, tool=54
content_chars=201,279
tool_calls=54
tool_results=54
```

Remote `gpt-5.5` Codex OAuth smoke results:

```text
variant                replacement_messages  replacement_chars  likely_resumable
current                3                     2,983              false
conversion-parity      3                     2,983              false
payload-parity         3                     2,983              false
preprocessing-parity   2                     1,234              false
builtin                103                   33,433             n/a
```

### Revised interpretation

Do **not** conclude that `/responses/compact` itself is low quality from this smoke alone.

The better current hypothesis is:

> The plugin is not yet sending a Codex-equivalent compact request. The endpoint returned selected history items because the payload lacked critical context that Codex normally sends.

Evidence from structural payload inspection:

```text
system/developer messages=0
assistant with codex_message_items=0
assistant with codex_reasoning_items=0
instruction_chars=0
tools=0
function_call=54
function_call_output=54
```

This means the endpoint saw many tool calls/results but no base instructions, no tool schemas, and no native Codex raw ResponseItem metadata.

### Codex implementation facts

Codex has at least two relevant compaction paths.

#### 1. Remote compact path: `ResponsesCompact`

Source references:

```text
/tmp/openai-codex/codex-rs/core/src/compact_remote.rs
/tmp/openai-codex/codex-rs/core/src/client.rs
/tmp/openai-codex/codex-rs/codex-api/src/common.rs
/tmp/openai-codex/codex-rs/codex-api/src/endpoint/compact.rs
```

Codex remote compact sends:

```text
model
input = history.for_prompt(...), then prompt.get_formatted_input()
instructions = base_instructions.text
tools = tool_router.model_visible_specs(), converted to Responses tool JSON
parallel_tool_calls = model capability
reasoning = build_reasoning(model_info, effort, summary)
text = verbosity/output-schema controls when applicable
```

It also sends identity/session headers such as:

```text
x-codex-installation-id
x-codex-window-id
session_id
x-codex-parent-thread-id when applicable
x-openai-subagent when applicable
```

The plugin currently sends auth/Cloudflare/account headers but not these Codex identity/session headers.

#### 2. Local-style compact path: `Responses`

Source references:

```text
/tmp/openai-codex/codex-rs/core/src/compact.rs
/tmp/openai-codex/codex-rs/core/templates/compact/prompt.md
/tmp/openai-codex/codex-rs/core/templates/compact/summary_prefix.md
```

This path runs a normal model inference with an explicit summary prompt:

```text
You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
```

Then it wraps the assistant summary with `summary_prefix.md` and builds replacement history.

Decision: the user-facing impression that “Codex compact is smart” may come from either the remote endpoint with native Codex history, the local-style prompt path, or the combination. We need to test them separately.

### 2026-05-01 official implementation re-check

Source checkout:

```text
/tmp/openai-codex-sparse
openai/codex main f50c02d7bcd4c06a23173389da8ed2c68c03d81d
```

Relevant files:

```text
codex-rs/core/src/client.rs
codex-rs/core/src/compact.rs
codex-rs/core/src/compact_remote.rs
codex-rs/core/src/tasks/compact.rs
codex-rs/protocol/src/models.rs
codex-rs/codex-api/src/endpoint/compact.rs
codex-rs/codex-api/src/requests/headers.rs
codex-rs/tools/src/tool_spec.rs
codex-rs/models-manager/models.json
```

Updated findings:

- Official remote compaction calls `/responses/compact`, but it is not treated like a plaintext summary endpoint. Tests model the successful response as `ResponseItem::Compaction { encrypted_content }`, with serde alias `compaction_summary`.
- The compacted item is later mounted back into the conversation history as a native Codex `ResponseItem`, not converted into a visible user/assistant summary message.
- Official regular `/responses` calls request `include = ["reasoning.encrypted_content"]` when reasoning is enabled, and history can therefore contain encrypted reasoning items. Our Hermes JSONL fixture is already lossy: it has no native encrypted reasoning items and no native compaction items.
- Official remote compact payload is built from `Prompt`, not raw chat messages: `prompt.get_formatted_input()`, `prompt.base_instructions.text`, `prompt.tools`, model-specific reasoning/text settings, and Codex session identity headers.
- Official remote compact sends `x-codex-installation-id`, `x-codex-window-id`, and `session_id`. Our plugin currently sends Codex auth/Cloudflare headers but not these session/window identity headers.
- Official tools are serialized directly from Codex `ToolSpec`. Our `instructed-tools-remote` variant only injects a minimal approximation inferred from fixture tool names, not the active Codex/Hermes model-visible tool registry.
- For normal `/responses`, Codex uses `store = provider.is_azure_responses_endpoint()`, `stream = true`, `tool_choice = "auto"`, `prompt_cache_key = conversation_id`, `client_metadata[x-codex-installation-id]`, and `include` for encrypted reasoning. The local-style smoke only approximates part of this.

Revised judgment:

`/responses/compact` should no longer be judged as “bad endpoint quality” from the current smoke. The smoke is not equivalent to Codex runtime because it lacks native encrypted reasoning/compaction history, exact `ToolSpec` schemas, and Codex session/window identity. The remote path may be designed to produce an opaque encrypted checkpoint for Codex’s own next-turn context rather than a readable Hermes handoff summary.

Implication for Hermes:

- If Hermes needs a visible replacement history, local-style explicit summary remains the practical path.
- If we want to test remote compact fairly, the next experiment should be a Codex-native fixture: capture/export actual Codex `ResponseItem` history including `reasoning.encrypted_content` and any `compaction` items, then replay that payload shape with Codex identity/session headers.
- Without native Codex encrypted items, repeatedly tweaking prompt text/tool names around a Hermes JSONL fixture is unlikely to prove remote compact parity.

---

## Non-goals

- Do not switch production runtime config to `context.engine: codex_compact`.
- Do not add Hermes built-in compressor fallback yet.
- Do not edit Hermes core.
- Do not read `~/.hermes/auth.json` or `~/.codex/auth.json` directly.
- Do not commit private fixtures, raw payloads, raw responses, OAuth tokens, API keys, Authorization headers, or session content.
- Do not treat raw `tests/fixtures/private/` outputs as source-controlled artifacts.
- Do not optimize for compression ratio alone; resumability and handoff quality matter more.

---

## Acceptance criteria

### Tests

Run from plugin repo root:

```bash
python -m pytest -q
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py tests/*.py
```

Expected:

```text
73+ passed, 1 skipped
py_compile OK
```

### Plugin discovery

Run from Hermes repo:

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

### Private artifact safety

```bash
git status --short --ignored
```

Expected private/runtime artifacts remain ignored:

```text
!! tests/fixtures/private/
!! .pytest_cache/
!! __pycache__/
```

---

## Commit strategy

Use small commits and push each stable milestone:

```text
feat: add codex compact base instructions
feat: add fixture tool schema injection
feat: wire compact focus topic into smoke payloads
feat: add codex local-style compact smoke
feat: compare remote and local codex compact modes
```

Do not bundle remote smoke result docs with code unless the docs describe that exact milestone.

---

# Phase 1: Make remote compact payload non-empty and Codex-like

## Task 1: Add base instructions config and payload support

**Objective:** Ensure compact payloads can send non-empty `instructions` even when exported Hermes fixtures lack `system` / `developer` messages.

**Files:**

- Modify: `config.py`
- Modify: `compact_preprocess.py`
- Modify: `engine.py`
- Modify: `scripts/smoke_compact.py`
- Test: `tests/test_compact_preprocess.py`
- Test: `tests/test_smoke_fixture.py`

**Design:**

Add config fields:

```python
base_instructions: str = ""
base_instructions_file: str = ""
```

Add helper behavior:

- If converted message instructions are non-empty, preserve them by default.
- If converted message instructions are empty and `base_instructions` or `base_instructions_file` is configured, use that text.
- In smoke scripts, provide a Codex/Hermes compact base instruction option without requiring production config changes.

Recommended default smoke instruction:

```text
You are Hermes Agent, a coding and task-execution agent. You are compacting a prior agent session for future continuation. The input contains user requests, assistant progress, and structured tool calls/results. Preserve the user's goal, decisions, completed work, relevant files, commands, constraints, blockers, and next steps. Do not copy raw tool output unless it is necessary to resume.
```

**Step 1: Write failing tests**

Add tests that assert:

- empty fixture instructions can be filled by explicit base instructions;
- existing system instructions are not silently overwritten unless an explicit override is requested;
- `dry_run_summary` reports non-zero `instruction_chars` for the new smoke option.

**Step 2: Run RED**

```bash
python -m pytest tests/test_compact_preprocess.py tests/test_smoke_fixture.py -q
```

Expected: new tests fail.

**Step 3: Implement minimal code**

- Add config fields.
- Add `base_instructions` argument to `build_codex_compact_payload()`.
- Add smoke flag such as `--base-instructions-mode {none,hermes-compact}` or `--base-instructions-file`.
- Keep default behavior backward-compatible unless variant explicitly enables it.

**Step 4: Run GREEN**

```bash
python -m pytest tests/test_compact_preprocess.py tests/test_smoke_fixture.py -q
```

**Step 5: Commit and push**

```bash
git add config.py compact_preprocess.py engine.py scripts/smoke_compact.py tests/test_compact_preprocess.py tests/test_smoke_fixture.py
git commit -m "feat: add codex compact base instructions"
git push
```

---

## Task 2: Add a new smoke variant for instructed remote compact

**Objective:** Compare old remote payloads against a new remote payload with Codex/Hermes base instructions.

**Files:**

- Modify: `scripts/smoke_compact.py`
- Modify: `README.md`
- Test: `tests/test_smoke_fixture.py`

**Design:**

Add variant:

```text
instructed-remote
```

This variant should be equivalent to `payload-parity` plus non-empty base instructions.

**Step 1: Write failing test**

Assert:

```python
payload, _ = build_payload_from_fixture(..., variant="instructed-remote")
assert len(payload["instructions"]) > 0
assert payload["parallel_tool_calls"] is True
```

**Step 2: Run RED**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

**Step 3: Implement variant**

Update `VARIANTS` and `variant_overrides()`.

**Step 4: Dry-run private fixture structure only**

```bash
python scripts/smoke_compact.py \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --variant instructed-remote
```

Expected:

```text
instruction_chars > 0
tools may still be 0 in this task
```

**Step 5: Commit and push**

```bash
git add scripts/smoke_compact.py tests/test_smoke_fixture.py README.md
git commit -m "feat: add instructed remote compact variant"
git push
```

---

# Phase 2: Add model-visible tool schemas

## Task 3: Add minimal fixture tool schema map

**Objective:** Stop sending many `function_call` items with `tools=[]` during private fixture smoke.

**Files:**

- Create: `tool_schemas.py`
- Modify: `compact_preprocess.py`
- Modify: `scripts/smoke_compact.py`
- Test: `tests/test_tool_schemas.py`
- Test: `tests/test_compact_preprocess.py`

**Design:**

Start with a small static schema map for observed fixture tool names:

```text
skill_view
terminal
read_file
search_files
patch
write_file
todo
```

Schemas can be minimal but should include descriptions and basic parameter objects. This is for smoke fidelity, not final production tool discovery.

**Step 1: Write failing tests**

Test that:

- `fixture_tool_schemas(["terminal", "read_file"])` returns Responses-compatible function tools;
- unknown names are skipped;
- `build_codex_compact_payload(..., tools=...)` reports `tools > 0`.

**Step 2: Run RED**

```bash
python -m pytest tests/test_tool_schemas.py tests/test_compact_preprocess.py -q
```

**Step 3: Implement minimal static map**

Create `tool_schemas.py` with:

```python
def minimal_fixture_tool_schemas(tool_names: Iterable[str]) -> list[dict[str, Any]]:
    ...
```

Return chat-style tool schema or Responses-style schema consistently, then reuse existing `responses_tools_from_chat_tools()` if needed.

**Step 4: Run GREEN**

```bash
python -m pytest tests/test_tool_schemas.py tests/test_compact_preprocess.py -q
```

**Step 5: Commit and push**

```bash
git add tool_schemas.py compact_preprocess.py scripts/smoke_compact.py tests/test_tool_schemas.py tests/test_compact_preprocess.py
git commit -m "feat: add fixture tool schema injection"
git push
```

---

## Task 4: Add tool-schema smoke variant

**Objective:** Create a variant that sends both base instructions and model-visible tool schemas.

**Files:**

- Modify: `scripts/smoke_compact.py`
- Modify: `README.md`
- Test: `tests/test_smoke_fixture.py`

**Design:**

Add variant:

```text
instructed-tools-remote
```

It should:

- use core message shape;
- use `codex_base_only` instruction policy;
- set `parallel_tool_calls=true`;
- use non-empty compact base instructions;
- infer fixture tool names from assistant `tool_calls`;
- inject minimal tool schemas.

**Step 1: Write failing test**

Assert for synthetic or private-independent fixture:

```python
payload, _ = build_payload_from_fixture(..., variant="instructed-tools-remote")
assert len(payload["instructions"]) > 0
assert len(payload["tools"]) > 0
```

**Step 2: Run RED**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

**Step 3: Implement variant**

Wire tool schema inference in `build_payload_from_fixture()`.

**Step 4: Dry-run private fixture**

```bash
python scripts/smoke_compact.py \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --variant instructed-tools-remote
```

Expected:

```text
instruction_chars > 0
tools > 0
function_call/function_call_output remain structured
```

**Step 5: Commit and push**

```bash
git add scripts/smoke_compact.py tests/test_smoke_fixture.py README.md
git commit -m "feat: add instructed tool-schema compact variant"
git push
```

---

# Phase 3: Fix smoke focus-topic semantics

## Task 5: Wire `--focus-topic` into smoke payloads safely

**Objective:** Ensure the smoke command's `--focus-topic` actually changes the compact instruction context when explicitly provided.

**Files:**

- Modify: `scripts/smoke_compact.py`
- Modify: `compact_preprocess.py` if instruction composition belongs there
- Test: `tests/test_smoke_fixture.py`

**Design:**

For smoke only, append focus text to the compact base instructions, not to raw history:

```text
Focus especially on: <focus_topic>
```

This is not exact Codex remote parity, so keep it explicit and documented as smoke guidance.

**Step 1: Write failing test**

Assert:

```python
payload = build_payload(..., focus_topic="quality comparison", variant="instructed-remote")
assert "quality comparison" in payload["instructions"]
```

**Step 2: Run RED**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

**Step 3: Implement**

Update `build_payload()` / `build_payload_from_fixture()`.

**Step 4: Run GREEN**

```bash
python -m pytest tests/test_smoke_fixture.py -q
```

**Step 5: Commit and push**

```bash
git add scripts/smoke_compact.py compact_preprocess.py tests/test_smoke_fixture.py
git commit -m "feat: wire compact focus topic into smoke payloads"
git push
```

---

# Phase 4: Compare against Codex local-style compaction

## Task 6: Add Codex compact prompt templates

**Objective:** Preserve Codex local-style compact prompt and summary prefix in the plugin for controlled comparison.

**Files:**

- Create: `templates/codex_compact_prompt.md`
- Create: `templates/codex_summary_prefix.md`
- Modify: `README.md`
- Test: `tests/test_local_style_compact.py`

**Template content:**

`templates/codex_compact_prompt.md`:

```text
You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
```

`templates/codex_summary_prefix.md`:

```text
Another language model started to solve this problem and produced a summary of its thinking process. You also have access to the state of the tools that were used by that language model. Use this to build on the work that has already been done and avoid duplicating work. Here is the summary produced by the other language model, use the information in this summary to assist with your own analysis:
```

**Step 1: Write tests**

Assert files exist and are non-empty.

**Step 2: Commit and push**

```bash
git add templates/ tests/test_local_style_compact.py README.md
git commit -m "feat: add codex compact prompt templates"
git push
```

---

## Task 7: Add local-style compact smoke script path

**Objective:** Test the second Codex compaction path: normal model inference with the explicit compact prompt, then summary-prefix replacement history.

**Files:**

- Create or modify: `scripts/smoke_local_style_compact.py` or extend `scripts/smoke_compact.py`
- Create: `local_style_compact.py`
- Test: `tests/test_local_style_compact.py`

**Design:**

Keep this separate from `/responses/compact` in code and metrics.

Pipeline:

```text
fixture messages
→ convert/sanitize history for normal model request
→ append compact prompt as user input
→ call normal Responses/chat model endpoint through existing safe client path if available
→ extract final assistant text
→ wrap with summary_prefix
→ build Hermes replacement history
→ evaluate handoff quality
```

If implementing the actual model call is too broad for this task, first implement fake-client tests and dry-run payload construction only.

**Step 1: Write fake-client tests**

Test that a fake summary becomes:

```text
<summary_prefix>
<summary>
```

inside a user-role replacement message.

**Step 2: Implement dry-run path**

Do not call remote API by default.

**Step 3: Commit and push**

```bash
git add local_style_compact.py scripts/smoke_compact.py tests/test_local_style_compact.py
git commit -m "feat: add codex local-style compact smoke"
git push
```

---

# Phase 5: Remote smoke comparison after payload fixes

## Task 8: Run private remote smoke A/B

**Objective:** Re-test remote compact quality only after base instructions and tool schemas are present.

**Files:**

- Modify: `README.md`
- Modify: this plan or create a result note under `.hermes/plans/`

**Commands:**

```bash
fixture='tests/fixtures/private/context-compression-real.jsonl'
for variant in instructed-remote instructed-tools-remote; do
  python scripts/smoke_compact.py \
    --auth-mode codex_oauth \
    --model gpt-5.5 \
    --fixture "$fixture" \
    --focus-topic 'Hermes ContextEngine plugin real-session compression test' \
    --variant "$variant" \
    --execute > "tests/fixtures/private/remote-smoke-next-${variant}.json"
done
```

Then summarize without raw private content:

```bash
python - <<'PY'
import json
from pathlib import Path
for p in sorted(Path('tests/fixtures/private').glob('remote-smoke-next-*.json')):
    data = json.loads(p.read_text())
    repl = data.get('replacement') or []
    q = data.get('handoff_quality') or {}
    chars = sum(len(str(m.get('content') or '')) for m in repl if isinstance(m, dict))
    print(p.name, 'messages=', len(repl), 'chars=', chars, 'likely_resumable=', q.get('likely_resumable'))
PY
```

**Expected signal:**

At least one instructed variant should improve over previous results by producing a replacement that contains some of:

```text
Active Task / current goal
completed actions / progress
remaining work / next steps
relevant files / commands
latest user direction
```

If still false, do not keep patching blindly; compare local-style path next.

**Commit docs only:**

```bash
git add README.md .hermes/plans/<result-note>.md
git commit -m "docs: record instructed codex compact smoke"
git push
```

---

## Task 9: Run local-style smoke comparison

**Objective:** Determine whether Codex's explicit compact prompt path is the source of higher perceived quality.

**Command shape:**

```bash
python scripts/smoke_compact.py \
  --mode local-style \
  --auth-mode codex_oauth \
  --model gpt-5.5 \
  --fixture tests/fixtures/private/context-compression-real.jsonl \
  --focus-topic 'Hermes ContextEngine plugin real-session compression test' \
  --execute > tests/fixtures/private/local-style-smoke-next.json
```

Use the actual command implemented in Task 7.

**Executed 2026-04-30:** remote and local-style smoke were run with `gpt-5.5` and Codex OAuth. Private JSON outputs are stored only under ignored `tests/fixtures/private/remote-smoke-20260430-*` directories.

```text
variant                         replacement_messages  replacement_chars  likely_resumable
current-remote                  3                     2,985              false
instructed-remote               3                     2,985              false
instructed-tools-remote         3                     2,985              false
preprocessing-parity-remote     2                     1,235              false
instructed-tools-local-style    1                     12,428             false
```

Execution surfaced two real API requirements and both were fixed:

- fixture `todo.todos` schema needs array `items`;
- normal Responses local-style path needs `store=false` and `stream=true`, plus SSE response parsing.

**Expected signal:**

Local-style output should look closer to a handoff summary than raw remote selected items. If it does, the plugin should treat `/responses/compact` and local-style compact as separate engines/modes, not conflate them.

---

# Phase 6: Decision point

After Tasks 8 and 9, decide among:

## Option A: Remote compact becomes viable

If instructed/tool-schema remote compact becomes resumable, continue improving remote parity:

- active Hermes tool schema discovery instead of fixture map;
- Codex identity/session headers where safe;
- better native ResponseItem preservation from Hermes sessions;
- production safety checks.

## Option B: Local-style compact is clearly better

If local-style compact is better, make it first-class:

- add explicit config mode, e.g. `codex_compact.mode: local_style | remote`;
- keep remote as experimental;
- use Codex prompt/prefix semantics;
- continue fixture A/B against built-in compressor.

## Option C: Both are poor on Hermes chat fixtures

If both fail, the root problem may be Hermes session export lossiness. Investigate:

- storing richer Codex Responses metadata in Hermes runtime histories;
- exporting native compact fixtures from live sessions;
- building a Hermes-specific task-log representation before compaction.

Do not activate runtime engine until one option consistently produces useful resumable handoffs.

---

## Documentation updates required

After implementation, update:

- `README.md` — config knobs, smoke variants, safety notes, result table;
- `AGENTS.md` — start-here plan references and current recommended workflow;
- `.hermes/plans/2026-04-30-codex-compact-remote-payload-investigation.md` — link to this follow-up plan or summarize superseding decisions.

---

## Safety checklist

Before each commit:

```bash
git status --short --ignored
```

Confirm:

- no files under `tests/fixtures/private/` are staged;
- no raw payload/response JSON is staged;
- no token, API key, Authorization header, or auth JSON content is staged;
- only intended source/docs/tests are staged.

Before any remote API smoke:

- confirm `--execute` is intentional;
- do not print raw payload or raw response into committed docs;
- summarize structure and quality metrics only.

---

## Current recommended next action

Phase 1〜5 の implementation/smoke は完了。2026-05-01 の公式実装再確認により、次の優先は Phase 6 の前に remote compact parity の前提を分け直すこと。

Recommended order:

- First, treat `/responses/compact` as a Codex-native opaque checkpoint path, not as a readable summary endpoint.
- Add a small parity test/documentation task for `ResponseItem::Compaction { encrypted_content }` handling so our postprocess does not pretend it can extract plaintext from remote compact output.
- If remote parity is still worth testing, capture a Codex-native fixture with raw `ResponseItem` history, including `reasoning.encrypted_content` and any existing `compaction` items, plus session/window header shape. Do not use the lossy Hermes JSONL fixture for that conclusion.
- Do not include local-style output review in this implementation slice.

Current judgment: remote `/responses/compact` may still be correct inside Codex, but current Hermes fixture cannot fairly evaluate it because it lacks native encrypted Codex state. Local-style review is intentionally not part of the next implementation slice.

Next implementation plan:

```text
.hermes/plans/2026-05-01-codex-remote-native-parity.md
```

This plan implements only items 1〜4: opaque remote compaction semantics, encrypted compaction handling, Codex-native fixture replay, and Codex session/window identity headers. It explicitly excludes local-style quality review.
