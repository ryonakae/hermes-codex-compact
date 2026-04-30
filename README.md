# hermes-codex-compact

Experimental Hermes Agent `ContextEngine` plugin that compacts conversation history by calling OpenAI/Codex `responses/compact` endpoints.

This is a PoC. It is intentionally small: conversion helpers, a remote compact client, and a `codex_compact` context engine. Durable checkpoints, retrieval tools, quality evaluation, and built-in compressor fallback are future work.

## What it does

`CodexCompactEngine.compress()` currently:

1. Converts Hermes/OpenAI-format chat messages into Codex-like Responses `ResponseItem` dictionaries.
2. Builds a Codex-like compact payload with `input`, `instructions`, `tools`, and `parallel_tool_calls`.
3. Calls a compact endpoint.
4. Prefers structured compact `output` items when present, falling back to `output_text` checkpoint wrapping.
5. Converts the compacted result back into valid Hermes chat messages, optionally preserving a recent tail.

The plugin deliberately avoids flattening tool calls/results into giant text blobs by default. Tool calls become `function_call` items and tool results become `function_call_output` items before `/responses/compact` is called.

## Configuration

Enable the plugin and select the context engine in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - hermes-codex-compact

context:
  engine: codex_compact

codex_compact:
  auth_mode: api_key       # api_key | codex_oauth | auto
  model: gpt-5.1-codex
  threshold: 0.85
  recent_tail_messages: 8
  max_tool_result_chars: 4000
  max_input_item_chars: null
  message_shape: response_item       # response_item | core
  instruction_policy: all_instructions # all_instructions | codex_base_only
  missing_tool_output_policy: drop # drop | keep | aborted
  preprocessing_mode: safe_truncate # safe_truncate | codex_parity
  parallel_tool_calls: false
  reasoning_effort: null
  reasoning_summary: null
  verbosity: null
  base_instructions: ""
  base_instructions_file: ""
  request_timeout_seconds: 120
  debug_dump: false
```

### Auth modes

- `api_key`: calls `https://api.openai.com/v1/responses/compact` using `OPENAI_API_KEY` or `codex_compact.openai_api_key`.
- `codex_oauth`: calls `https://chatgpt.com/backend-api/codex/responses/compact` using Hermes `openai-codex` OAuth credentials.
- `auto`: prefers API key if available, otherwise Codex OAuth.

Codex OAuth is experimental. The plugin uses Hermes credential resolver helpers and does not read `~/.hermes/auth.json` or `~/.codex/auth.json` directly.

### Codex parity knobs

- `message_shape: core` makes normal user/assistant/developer inputs use the same `{role, content}` shape as Hermes' Codex Responses adapter. `response_item` keeps the earlier explicit `{type: message, ...}` shape.
- `instruction_policy: codex_base_only` keeps only system/base instructions in the compact `instructions` field and leaves developer context in `input`, closer to Codex remote compact. `all_instructions` keeps the previous behavior.
- `parallel_tool_calls`, `reasoning_effort`, `reasoning_summary`, and `verbosity` are passed through to the compact payload when configured.
- `missing_tool_output_policy: aborted` mirrors Codex-style interrupted tool calls by synthesizing a `function_call_output` with `output: "aborted"` instead of dropping the call.
- `preprocessing_mode: codex_parity` avoids pre-truncating large tool outputs while the request remains under the configured budget; `safe_truncate` keeps the earlier conservative truncation behavior.

## Development

Run tests from the repo root:

```bash
python -m pytest -q
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py tests/*.py
```

Dry-run the smoke payload without network access:

```bash
python scripts/smoke_compact.py --auth-mode api_key
```

Use a real exported session fixture without changing `context.engine`:

```bash
# Writes into tests/fixtures/private/ by default; that directory is gitignored.
python scripts/export_session_fixture.py --session-id <session-id>

# Dry-run conversion and replacement-history preview from a private fixture.
python scripts/smoke_compact.py \
  --fixture tests/fixtures/private/<session-id>.jsonl \
  --focus-topic "context compression" \
  --compare-builtin

# Compare parity variants without network access.
python scripts/smoke_compact.py --fixture tests/fixtures/private/<session-id>.jsonl --variant current
python scripts/smoke_compact.py --fixture tests/fixtures/private/<session-id>.jsonl --variant conversion-parity
python scripts/smoke_compact.py --fixture tests/fixtures/private/<session-id>.jsonl --variant payload-parity
python scripts/smoke_compact.py --fixture tests/fixtures/private/<session-id>.jsonl --variant preprocessing-parity
python scripts/smoke_compact.py --fixture tests/fixtures/private/<session-id>.jsonl --variant instructed-remote
python scripts/smoke_compact.py --fixture tests/fixtures/private/<session-id>.jsonl --variant instructed-tools-remote
```

`instructed-remote` keeps the remote `/responses/compact` path but fills `instructions` with a Hermes/Codex compact base instruction when the fixture has no system/developer messages. Use it to test whether the prior poor output was caused by sending `instructions: ""`.

`instructed-tools-remote` additionally injects minimal Responses-compatible function tool schemas inferred from fixture tool calls. This is still a smoke-test approximation, not the final Hermes active tool registry integration.

Actually call the remote API only when you intend to spend tokens / use OAuth credentials:

```bash
python scripts/smoke_compact.py --auth-mode api_key --execute
python scripts/smoke_compact.py --auth-mode codex_oauth --execute
python scripts/smoke_compact.py --auth-mode codex_oauth --fixture tests/fixtures/private/<session>.jsonl --variant preprocessing-parity --execute
```

### 2026-04-30 private real-session remote smoke

Ignored private fixture used:

```text
tests/fixtures/private/context-compression-real.jsonl
```

Fixture summary:

```text
messages=107
content_chars=201,279
tool_calls=54
tool_results=54
```

Remote Codex OAuth smoke was executed for all variants with `gpt-5.5`. Results were stored under ignored `tests/fixtures/private/remote-smoke-20260430/`; do not commit those files.

```text
variant                replacement_messages  replacement_chars  likely_resumable
current                3                     2,983              false
conversion-parity      3                     2,983              false
payload-parity         3                     2,983              false
preprocessing-parity   2                     1,234              false
builtin                103                   33,433             n/a
```

Takeaway: parity conversion/payload changes made the request shape closer to Codex, but this endpoint still returned selected history items rather than a Hermes-quality resumable handoff summary for this fixture. `preprocessing-parity` was worse because less conservative preprocessing produced an even shorter selected-item replacement. Do not switch production `context.engine` to `codex_compact` based on these results.

Private real-session fixture tests are opt-in:

```bash
RUN_CODEX_COMPACT_PRIVATE=1 python -m pytest tests/test_session_fixtures.py -q
```

## Private API dependency

For Codex OAuth headers, this PoC uses Hermes private helper `agent.auxiliary_client._codex_cloudflare_headers`. Keep that dependency isolated in `auth.py`. If this plugin becomes production-quality, prefer a public Hermes helper or a stable wrapper.

## Safety notes

- Do not log tokens or Authorization headers.
- Do not directly parse or refresh Codex auth JSON files.
- Do not store raw compact payloads/responses by default; they may contain private conversation and tool output.
- Treat `chatgpt.com/backend-api/codex` as experimental, not a stable public API.
