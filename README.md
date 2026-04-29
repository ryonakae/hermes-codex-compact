# hermes-codex-compact

Experimental Hermes Agent `ContextEngine` plugin that compacts conversation history by calling OpenAI/Codex `responses/compact` endpoints.

This is a PoC. It is intentionally small: conversion helpers, a remote compact client, and a `codex_compact` context engine. Durable checkpoints, retrieval tools, quality evaluation, and built-in compressor fallback are future work.

## What it does

`CodexCompactEngine.compress()` currently:

1. Lightly prepares Hermes/OpenAI-format messages.
2. Converts them into a Responses compact payload.
3. Calls a compact endpoint.
4. Extracts compacted text.
5. Returns replacement history shaped as:

```text
[original system/developer messages]
[user message: compact checkpoint]
[recent safe tail messages]
```

The checkpoint message is a historical handoff, not a new user request.

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
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py scripts/smoke_compact.py tests/*.py
```

Dry-run the smoke payload without network access:

```bash
python scripts/smoke_compact.py --auth-mode api_key
```

Actually call the remote API only when you intend to spend tokens / use OAuth credentials:

```bash
python scripts/smoke_compact.py --auth-mode api_key --execute
python scripts/smoke_compact.py --auth-mode codex_oauth --execute
```

## Private API dependency

For Codex OAuth headers, this PoC uses Hermes private helper `agent.auxiliary_client._codex_cloudflare_headers`. Keep that dependency isolated in `auth.py`. If this plugin becomes production-quality, prefer a public Hermes helper or a stable wrapper.

## Safety notes

- Do not log tokens or Authorization headers.
- Do not directly parse or refresh Codex auth JSON files.
- Do not store raw compact payloads/responses by default; they may contain private conversation and tool output.
- Treat `chatgpt.com/backend-api/codex` as experimental, not a stable public API.
