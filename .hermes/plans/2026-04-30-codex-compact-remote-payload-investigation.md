# Codex Compact Remote Payload Investigation

Date: 2026-04-30

## Question

The previous remote smoke concluded that `/responses/compact` returned selected history items rather than a Hermes-quality structured handoff summary. The user pointed out a more likely cause: the plugin may not be sending information in the same way Codex actually does.

This investigation compares the current `hermes-codex-compact` payload against Codex's actual implementation and the private fixture structure, without committing private fixture contents or raw payloads/responses.

## References inspected

Codex source:

- `/tmp/openai-codex/codex-rs/core/src/compact_remote.rs`
- `/tmp/openai-codex/codex-rs/core/src/client.rs`
- `/tmp/openai-codex/codex-rs/core/src/client_common.rs`
- `/tmp/openai-codex/codex-rs/codex-api/src/common.rs`
- `/tmp/openai-codex/codex-rs/codex-api/src/endpoint/compact.rs`
- `/tmp/openai-codex/codex-rs/core/src/compact.rs`
- `/tmp/openai-codex/codex-rs/core/templates/compact/prompt.md`
- `/tmp/openai-codex/codex-rs/core/templates/compact/summary_prefix.md`

Hermes/plugin source:

- `responses_conversion.py`
- `compact_preprocess.py`
- `compact_postprocess.py`
- `client.py`
- `engine.py`
- `scripts/smoke_compact.py`
- `~/.hermes/hermes-agent/agent/codex_responses_adapter.py`

## Key finding

The earlier interpretation was too strong. The endpoint may be behaving as designed for the low-quality/incomplete payload we sent. The smoke fixture and plugin payload are materially different from actual Codex remote compaction input.

The main evidence: for the real-session fixture, the plugin payload contains no base instructions, no developer/context prefix, no tool schemas, no Codex raw ResponseItem metadata, and very little assistant narrative content.

## Private fixture structural summary

Fixture: `tests/fixtures/private/context-compression-real.jsonl` (ignored, not committed)

```text
messages=107
roles: user=2, assistant=51, tool=54
content_chars=201,279
tool_calls=54
tool_results=54
system/developer messages=0
assistant with codex_message_items=0
assistant with codex_reasoning_items=0
assistant with tool_calls=49
tool messages=54
tool name field on tool messages: empty for all 54
```

This is already a lossy Hermes chat-format export. It is not Codex's native `ContextManager` history.

## Payload structure produced by plugin

For `current`:

```text
payload keys: input, instructions, model, parallel_tool_calls, tools
input_items=113
instruction_chars=0
tools=0
parallel_tool_calls=false
reasoning=None
text=None
item types: message=5, function_call=54, function_call_output=54
visible chars: function_call=37,390; function_call_output=89,014; message=5,668
```

For `conversion-parity` / `payload-parity`:

```text
input_items=113
instruction_chars=0
tools=0
item types: user=2, assistant=3, function_call=54, function_call_output=54
visible chars: user=1,234; assistant=4,434; function_call=37,390; function_call_output=89,014
```

For `preprocessing-parity`:

```text
input_items=113
instruction_chars=0
tools=0
item types: user=2, assistant=3, function_call=54, function_call_output=54
visible chars: user=1,234; assistant=4,434; function_call=37,390; function_call_output=195,611
```

The endpoint saw mostly structured tool calls/results and almost no instruction/user-facing assistant narrative.

## Codex actual remote compact flow

Codex remote compact does:

```text
sess.clone_history()
sess.get_base_instructions()
trim_function_call_history_to_fit_context_window(...)
history.for_prompt(input_modalities)
built_tools(...).model_visible_specs()
Prompt {
  input: prompt_input,
  tools: tool_router.model_visible_specs(),
  parallel_tool_calls: turn_context.model_info.supports_parallel_tool_calls,
  base_instructions,
  personality,
  output_schema: None,
  output_schema_strict: true,
}
model_client.compact_conversation_history(...)
process_compacted_history(...)
sess.replace_compacted_history(...)
```

`compact_conversation_history()` sends:

```text
model
input = prompt.get_formatted_input()
instructions = prompt.base_instructions.text
tools = create_tools_json_for_responses_api(prompt.tools)
parallel_tool_calls
reasoning = build_reasoning(model_info, effort, summary)
text = create_text_param_for_request(...)
```

It also sends additional headers:

```text
x-codex-installation-id
x-codex-window-id
session_id
x-codex-parent-thread-id when applicable
x-openai-subagent when applicable
```

The current plugin only sends the auth/Cloudflare/account headers plus content type.

## Critical differences from actual Codex

### 1. `instructions` is empty in the smoke payload

Codex always sends `base_instructions.text`. The smoke fixture has no `system` or `developer` messages, so the plugin sends `instructions: ""`.

This is not Codex-like. It deprives the endpoint of the agent identity, task semantics, tool-use expectations, and the fact that this is a coding-agent history.

This is likely the biggest issue.

### 2. No tool schemas

Codex sends `tool_router.model_visible_specs()` converted to Responses tool JSON. The plugin sends `tools: []`.

The payload has 54 `function_call` items, but the endpoint has no model-visible descriptions/parameters for `skill_view`, `terminal`, `read_file`, `patch`, `todo`, etc.

This likely makes the tool trajectory much harder to interpret.

### 3. Fixture is not native Codex history

Actual Codex compacts `ContextManager` raw `ResponseItem`s. The private fixture is Hermes chat-format JSONL.

It has:

- no `codex_message_items`
- no `codex_reasoning_items`
- no `phase`
- no encrypted reasoning continuity
- no native Codex `Compaction` items
- no initial context / developer prefix items

The parity code can only preserve those fields when present. For this fixture they are absent.

### 4. The smoke script ignores `focus_topic`

`--focus-topic` is accepted but not injected into the compact payload. This does not explain Codex parity, because Codex remote compact does not use a custom handoff prompt either, but it means our smoke command gave the endpoint no extra goal/context despite the CLI argument.

### 5. We may be testing the wrong Codex compaction mode

Codex has two compaction paths:

1. `ResponsesCompact` remote endpoint: `/responses/compact`, returns `Vec<ResponseItem>` replacement history.
2. `Responses` local-style compaction: sends `templates/compact/prompt.md` through normal model inference, then wraps the final assistant summary with `templates/compact/summary_prefix.md` into replacement history.

The known “Codex compact is smart” user-facing behavior may be largely from the second path, or from a combination of native Codex history + remote endpoint + postprocessing. The current plugin is testing only path 1 with lossy Hermes history.

### 6. Current postprocess does not fully mirror Codex filtering

Codex `process_compacted_history()` drops stale developer messages and non-real user prefix/context messages via `parse_turn_item`, then may reinject initial context.

The plugin keeps all user/assistant message items from output. This can preserve selected original user messages even when they are not useful handoff summaries. This is not the root cause of the endpoint output, but it affects final replacement quality.

## Revised conclusion

The earlier conclusion should be softened:

> The remote endpoint returned selected history items for our smoke fixture.

But the stronger explanation is now:

> The plugin is not yet sending a Codex-equivalent compact request. In particular, it sends empty instructions, no tool schemas, no native Codex ResponseItem metadata, and a lossy Hermes chat export. Therefore the remote endpoint result is not a fair test of actual Codex compact quality.

## Recommended next implementation experiments

Do these one at a time with private fixture smoke and deterministic metrics.

### Experiment A: Add explicit base instructions for compact smoke

Add `base_instructions` / `compact_instructions` config or smoke flag. For Hermes, this can be the current Hermes system prompt or a short Codex/Hermes coding-agent base instruction.

Goal: make `instructions` non-empty and comparable to Codex `base_instructions.text`.

Acceptance signal: output should contain a summary/checkpoint-like user message, not only original user messages.

### Experiment B: Inject model-visible tool schemas

Use Hermes tool registry schemas or a minimal fixture schema map for the observed tool names.

Goal: avoid sending 54 function calls with `tools=[]`.

Acceptance signal: tool trajectory is summarized semantically, with less raw tool-output residue.

### Experiment C: Build a Codex-style local compaction mode

Implement the second Codex path: append the compact prompt from `templates/compact/prompt.md`, run a normal model/Responses request, then wrap the summary with `summary_prefix.md`.

This may match the user-facing “Codex compact is smart” behavior better than `/responses/compact` alone.

### Experiment D: Capture/compare actual native Codex compaction payload shape

If feasible without leaking secrets, run native Codex with tracing or local instrumentation to capture structural request stats only:

- instruction length
- tool schema count/names
- item type counts
- role counts
- presence of compaction/context prefix items
- reasoning/text fields
- headers present by name only

Do not capture raw payload body by default.

## Safety

No raw private session content, payload body, remote response body, OAuth token, API key, or Authorization header was recorded in this report.
