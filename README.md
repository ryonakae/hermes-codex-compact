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
  request_timeout_seconds: 120
  debug_dump: false
```

### Auth modes

- `api_key`: calls `https://api.openai.com/v1/responses/compact` using `OPENAI_API_KEY` or `codex_compact.openai_api_key`.
- `codex_oauth`: calls `https://chatgpt.com/backend-api/codex/responses/compact` using Hermes `openai-codex` OAuth credentials.
- `auto`: prefers API key if available, otherwise Codex OAuth.

Codex OAuth is experimental. The plugin uses Hermes credential resolver helpers and does not read `~/.hermes/auth.json` or `~/.codex/auth.json` directly.

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
```

Actually call the remote API only when you intend to spend tokens / use OAuth credentials:

```bash
python scripts/smoke_compact.py --auth-mode api_key --execute
python scripts/smoke_compact.py --auth-mode codex_oauth --execute
python scripts/smoke_compact.py --auth-mode codex_oauth --fixture tests/fixtures/private/<session>.jsonl --execute
```

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
