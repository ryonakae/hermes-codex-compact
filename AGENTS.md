# AGENTS.md

`hermes-codex-compact` is an experimental Hermes Agent standalone plugin that registers a `codex_compact` `ContextEngine` and calls OpenAI/Codex `responses/compact` for context compression.

## Start here

- Read `.hermes/plans/2026-04-30_005014-hermes-codex-compact-poc.md` for the implementation roadmap.
- Read `README.md` for user-facing configuration and current limitations.
- Main entrypoints: `plugin.yaml`, `__init__.py`, `engine.py`, `client.py`, `responses_conversion.py`, `compact_preprocess.py`, `compact_postprocess.py`, `conversion.py`, `message_ops.py`.

## Common commands

```bash
python -m pytest -q
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py tests/*.py
python scripts/smoke_compact.py --auth-mode api_key
python scripts/smoke_compact.py --fixture tests/fixtures/synthetic_session.jsonl --compare-builtin
```

Use `--execute` with `scripts/smoke_compact.py` only when intentionally calling remote APIs.

## Development rules

- Keep Hermes core unchanged. This repo should remain a standalone plugin under `~/.hermes/plugins/hermes-codex-compact/`.
- The registered engine name is `codex_compact`; keep it in sync with docs and tests.
- Prefer pure conversion/message tests before changing compact behavior.
- Do not reintroduce flattened tool-output payloads as the default compact input. Hermes tool calls should remain structured as Responses `function_call` / `function_call_output` items.
- Keep real-session fixtures and compact result JSON under `tests/fixtures/private/`; they are gitignored and must never be staged.
- Never read `~/.hermes/auth.json` or `~/.codex/auth.json` directly.
- Do not implement Codex refresh-token handling in this plugin; use Hermes resolver helpers.
- Do not log tokens, Authorization headers, or raw compact payloads/responses by default.
- Treat `chatgpt.com/backend-api/codex` as experimental.

## Validation

Before commit/push, run:

```bash
python -m pytest -q
python -m py_compile __init__.py auth.py client.py config.py conversion.py engine.py message_ops.py responses_conversion.py compact_preprocess.py compact_postprocess.py session_fixtures.py scripts/export_session_fixture.py scripts/smoke_compact.py scripts/compare_builtin_fixture.py tests/*.py
```

For plugin discovery, run from the Hermes Agent repo after enabling the plugin in `~/.hermes/config.yaml` if needed:

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
