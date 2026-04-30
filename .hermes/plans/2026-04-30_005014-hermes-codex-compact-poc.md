# hermes-codex-compact PoC 実装計画

## 目的

Hermes Agent の `ContextEngine` plugin として、OpenAI / Codex の remote compact API を使う実験用 compression engine を作る。

最初の PoC では、堅牢な fallback、永続 checkpoint、retrieval tool、A/B 評価基盤は入れない。まず次を確認する。

1. Hermes の会話履歴を compact API に渡せる形へ変換できる。
2. OpenAI API key と Hermes の Codex OAuth credential の両方で compact API 呼び出しを試せる。
3. compact 結果を Hermes の message history に戻し、次 turn が壊れず継続できる。
4. manual `/compress` または threshold 発火で `ContextEngine.compress()` が動く。

## リポジトリ

```text
/Users/ryo.nakae/.hermes/plugins/hermes-codex-compact
```

plugin / repo 名は `hermes-codex-compact`。

ContextEngine 名は Python/config 上では snake_case にする。

```yaml
context:
  engine: codex_compact
```

## 前提・判断

- Hermes core は触らない。
- user/local standalone plugin として `~/.hermes/plugins/hermes-codex-compact/` に実装する。
- PoC は小さく始める。
- fallback は後回し。ただし失敗時に元履歴を破壊しない fail-safe は最低限入れる。
- OpenAI API key 経路と Codex OAuth 経路の両方を試せるようにする。
- Codex OAuth token は `~/.hermes/auth.json` や `~/.codex/auth.json` を直接読まない。
- Codex OAuth は Hermes の resolver を経由して取得する。
- `chatgpt.com/backend-api/codex/responses/compact` は experimental 扱いにする。
- `api.openai.com/v1/responses/compact` は公式 API key 経路として扱う。

## 参照する Hermes 実装

主な参照元。

```text
/Users/ryo.nakae/.hermes/hermes-agent/agent/context_engine.py
/Users/ryo.nakae/.hermes/hermes-agent/agent/context_compressor.py
/Users/ryo.nakae/.hermes/hermes-agent/run_agent.py
/Users/ryo.nakae/.hermes/hermes-agent/plugins/context_engine/__init__.py
/Users/ryo.nakae/.hermes/hermes-agent/hermes_cli/plugins.py
/Users/ryo.nakae/.hermes/hermes-agent/hermes_cli/auth.py
/Users/ryo.nakae/.hermes/hermes-agent/hermes_cli/runtime_provider.py
/Users/ryo.nakae/.hermes/hermes-agent/agent/auxiliary_client.py
/Users/ryo.nakae/.hermes/hermes-agent/agent/codex_responses_adapter.py
```

Codex 側の参照元。

```text
/tmp/openai-codex/codex-rs/core/src/compact.rs
/tmp/openai-codex/codex-rs/core/src/compact_remote.rs
/tmp/openai-codex/codex-rs/core/src/tasks/compact.rs
/tmp/openai-codex/codex-rs/core/src/session/turn.rs
/tmp/openai-codex/codex-rs/codex-api/src/endpoint/compact.rs
/tmp/openai-codex/codex-rs/core/templates/compact/prompt.md
/tmp/openai-codex/codex-rs/core/templates/compact/summary_prefix.md
```

## PoC のフェーズ設計

PoC は一気に完成形へ向かわず、段階ごとに「何が分かったら次へ進むか」を明確にする。

### Phase 0: repo skeleton / plan

目的:

- `hermes-codex-compact` repo を作る。
- 実装計画を `.hermes/plans/` に保存する。
- plugin 名、engine 名、auth mode、PoC scope を確定する。

完了条件:

- git repo が作成済み。
- plan が保存済み。
- 実装対象ファイルとテスト方針が明確。

### Phase 1: pure conversion PoC

目的:

- 外部 API を叩かず、Hermes messages を compact API 向け payload へ変換できるようにする。
- compact response の fake fixture から Hermes replacement history を作れるようにする。

実装対象:

- `conversion.py`
- `message_ops.py`
- `tests/test_conversion.py`
- `tests/test_message_ops.py`

完了条件:

- user / assistant / tool / system message を text 化できる。
- long tool result を truncate できる。
- compact summary から `[system] + [checkpoint summary] + [safe tail]` の replacement history を作れる。
- tool pair の片割れで次 API call が壊れないよう最低限 sanitize できる。

### Phase 2: ContextEngine fake-client PoC

目的:

- Hermes の `ContextEngine` として成立することを、実 API なしで確認する。

実装対象:

- `engine.py`
- `config.py`
- `tests/test_engine.py`

完了条件:

- `name == "codex_compact"`。
- `update_from_response()` / `should_compress()` が動く。
- fake client を注入した `compress()` が replacement history を返す。
- client error 時に少なくとも元履歴を壊さず返せる。

### Phase 3: OpenAI API key compact smoke

目的:

- 公式 `https://api.openai.com/v1/responses/compact` が PoC payload で実際に使えるか確認する。

実装対象:

- `client.py`
- optional: `scripts/smoke_compact.py`
- `tests/test_client_payload.py`

完了条件:

- API key mode の URL / headers / payload が正しい。
- 小さな fixture history で compact API call を試せる。
- response shape を確認し、`extract_compact_text()` を実データに合わせられる。
- token や Authorization header を log しない。

### Phase 4: Codex OAuth compact smoke

目的:

- Hermes の `openai-codex` OAuth credential を使い、Codex backend の `/responses/compact` が通るか確認する。

実装対象:

- `auth.py`
- `client.py` の `codex_oauth` mode
- optional: `scripts/smoke_compact.py --auth-mode codex_oauth`

完了条件:

- `resolve_codex_runtime_credentials()` 経由で access token / base URL を取得する。
- `_codex_cloudflare_headers()` 相当の header を付ける。
- `https://chatgpt.com/backend-api/codex/responses/compact` を叩ける、または 401/403/404 などの結果を安全に確認できる。
- `~/.hermes/auth.json` / `~/.codex/auth.json` を直接読まない。

### Phase 5: Hermes plugin integration PoC

目的:

- Hermes の standalone plugin として load され、manual `/compress` で実際に使えるか確認する。

実装対象:

- `plugin.yaml`
- `__init__.py`
- plugin registration
- README / AGENTS の最小記述

完了条件:

- plugin loader が `hermes-codex-compact` を発見する。
- `context.engine: codex_compact` で engine が選ばれる。
- manual `/compress` 後、次 turn が壊れず進む。
- 圧縮後履歴に compact checkpoint summary が入る。

### Phase 6: 実用化判断

目的:

- PoC の結果から、次にどこまで作り込むかを判断する。

判断項目:

- OpenAI API key 経路は安定して使えるか。
- Codex OAuth 経路は実用可能か、experimental のままにするべきか。
- Hermes built-in compressor より品質が良いケースがあるか。
- fallback / checkpoint store / retrieval tool を追加する価値があるか。
- Slack gateway 実運用に入れるべきか、CLI 実験に留めるべきか。

## PoC の全体フロー

```text
ContextEngine.compress(messages, current_tokens, focus_topic)
  ↓
1. Hermes messages を軽く sanitize / classify
  ↓
2. Hermes形式 → OpenAI Responses compact input 形式へ変換
  ↓
3. auth_mode に応じて compact endpoint を呼ぶ
   - api_key:      https://api.openai.com/v1/responses/compact
   - codex_oauth:  https://chatgpt.com/backend-api/codex/responses/compact
  ↓
4. compact response から summary / compacted text を抽出
  ↓
5. Hermes replacement history を構築
   - original system messages
   - compact checkpoint user message
   - recent safe tail
  ↓
6. replacement history を返す
```

## 最終的なゴール

最終的には、`hermes-codex-compact` を単なる API wrapper ではなく、Hermes 向けの実用的な Codex-inspired context engine に育てる。

### 最終形の目標

- Hermes built-in compressor と安全に切り替えられる experimental ContextEngine。
- OpenAI API key と Codex OAuth の両方を選べる auth mode。
- `responses/compact` の出力を Hermes に適した replacement history へ安定変換する。
- Codex の設計思想に近い checkpoint compaction を取り入れる。
  - recent user messages を厚めに保持する。
  - compact summary を handoff checkpoint として扱う。
  - 圧縮後履歴を replacement history として保存できるようにする。
- Hermes 独自の強みとして、将来的に context retrieval tool を追加できる余地を残す。
- Slack / gateway の長い会話でも、既存の Hermes built-in compressor より継続品質が良いか検証できる。

### 最終形で入れる可能性が高い機能

- built-in `ContextCompressor` fallback。
- SQLite checkpoint store。
- compact input / output の token estimate と品質ログ。
- `context_search` / `checkpoint_read` のような context engine tool。
- `focus_topic` 対応。
- Codex風 recent user messages budget。
- large tool output の structured pruning。
- secret redaction の強化。
- A/B comparison fixture。
- README / AGENTS / tests の公開 repo 水準への整備。

### 最終形でも避けること

- Hermes core の不要な変更。
- `~/.codex/auth.json` の直接利用。
- refresh token の独自管理。
- ChatGPT/Codex backend 経路を stable API として扱うこと。
- 圧縮対象の raw conversation を debug log に常時保存すること。

## 初期ファイル構成

```text
hermes-codex-compact/
├── plugin.yaml
├── __init__.py
├── engine.py
├── auth.py
├── client.py
├── conversion.py
├── message_ops.py
├── config.py
├── tests/
│   ├── test_engine.py
│   ├── test_conversion.py
│   ├── test_message_ops.py
│   └── test_client_payload.py
├── README.md
├── AGENTS.md
├── .gitignore
└── .hermes/
    └── plans/
        └── 2026-04-30_005014-hermes-codex-compact-poc.md
```

PoC では README / AGENTS は短くてよい。公開や共有を意識する段階で厚くする。

## plugin.yaml

最小案。

```yaml
name: hermes-codex-compact
version: 0.1.0
description: Experimental Hermes ContextEngine using OpenAI/Codex responses compact.
kind: standalone
```

ContextEngine 登録は `register(ctx)` で行う。

```python
from .engine import CodexCompactEngine


def register(ctx):
    ctx.register_context_engine(CodexCompactEngine())
```

Hermes の standalone plugin loader から読まれることを優先する。もし context engine directory 形式が必要になった場合は、後で `plugins/context_engine/<name>/` 方式も検討する。

## 設定設計

PoC では Hermes の `config.yaml` に plugin 固有 namespace を置く。

```yaml
plugins:
  enabled:
    - hermes-codex-compact

context:
  engine: codex_compact

codex_compact:
  auth_mode: api_key       # api_key | codex_oauth | auto
  model: gpt-5.1-codex     # PoC値。実際に responses/compact が受ける model を検証して調整
  threshold: 0.85
  recent_tail_messages: 8
  max_tool_result_chars: 4000
  request_timeout_seconds: 120
  debug_dump: false
```

`auth_mode` の意味。

- `api_key`
  - `OPENAI_API_KEY` または Hermes config/env から OpenAI API key を使う。
  - endpoint: `https://api.openai.com/v1/responses/compact`
- `codex_oauth`
  - Hermes の `openai-codex` OAuth credential resolver を使う。
  - endpoint: `https://chatgpt.com/backend-api/codex/responses/compact`
  - experimental。
- `auto`
  - PoC では後回し。最初は明示指定のみでもよい。

## ContextEngine 実装

`engine.py`。

```python
from agent.context_engine import ContextEngine


class CodexCompactEngine(ContextEngine):
    @property
    def name(self) -> str:
        return "codex_compact"

    def update_from_response(self, usage: dict) -> None:
        ...

    def should_compress(self, prompt_tokens: int | None = None) -> bool:
        ...

    def compress(self, messages: list, current_tokens: int | None = None, focus_topic: str | None = None) -> list:
        ...
```

必要属性。

```python
last_prompt_tokens = 0
last_completion_tokens = 0
last_total_tokens = 0
threshold_tokens = 0
context_length = 0
compression_count = 0
```

`update_model()` は PoC でも実装する。Hermes runtime から model / context_length が渡るため、threshold 計算に使う。

```python
def update_model(self, model=None, context_length=None, **kwargs):
    if context_length:
        self.context_length = context_length
        self.threshold_tokens = int(context_length * self.threshold_percent)
```

## `compress()` の PoC 挙動

1. 入力 `messages` を shallow copy する。
2. `message_ops.prepare_for_compact()` で軽く整理する。
3. `conversion.hermes_messages_to_compact_input()` で compact API payload を作る。
4. `client.compact(payload, auth_mode)` を呼ぶ。
5. `conversion.extract_compact_text(response)` で compact text を取り出す。
6. `message_ops.build_replacement_history(original_messages, compact_text, tail_messages)` で返却 history を作る。
7. `compression_count` を increment する。
8. 例外時は PoC では元 `messages` を返す。履歴破壊だけは避ける。

疑似コード。

```python
def compress(self, messages, current_tokens=None, focus_topic=None):
    try:
        prepared = prepare_for_compact(messages, max_tool_result_chars=self.max_tool_result_chars)
        payload = hermes_messages_to_compact_payload(
            prepared,
            model=self.model,
            focus_topic=focus_topic,
        )
        response = self.client.compact(payload)
        compact_text = extract_compact_text(response)
        replacement = build_replacement_history(
            original_messages=messages,
            compact_text=compact_text,
            recent_tail_messages=self.recent_tail_messages,
        )
        replacement = sanitize_tool_pairs(replacement)
        self.compression_count += 1
        return replacement
    except Exception as exc:
        self._last_error = str(exc)
        return messages
```

## メッセージ整理方針

PoC ではやりすぎない。

### やる

- `system` message は保持。
- `tool` message の `content` が長すぎる場合は truncate。
- `assistant.tool_calls` と `tool` result の半端な tail を避ける。
- `content` が list/dict の場合は readable text に落とす。
- image / binary / attachment 的 content は placeholder にする。

### やらない

- Codex の replacement history checkpoint 永続化。
- recent user messages 20k token 優先保持。
- rollout reconstruction。
- context diff baseline 再注入。
- retrieval tool。

## Hermes形式 → compact input 変換

`conversion.py` に置く。

PoC 方針: compact 用入力なので、tool call を実行可能な tool call として忠実に渡すより、文脈理解用 text に flatten する。

```python
def hermes_messages_to_compact_payload(messages, model, focus_topic=None):
    instructions = build_compact_instructions(focus_topic)
    input_items = []
    for msg in messages:
        item = hermes_message_to_responses_input_item(msg)
        if item:
            input_items.append(item)
    return {
        "model": model,
        "input": input_items,
        "instructions": instructions,
    }
```

変換方針。

- `role=user`
  - `{"role": "user", "content": text}`
- `role=assistant`
  - `{"role": "assistant", "content": text}`
  - `tool_calls` がある場合は content に `[Assistant requested tool call: ...]` を追記する。
- `role=tool`
  - `{"role": "user", "content": "[Tool result: <name/id>]\n..."}`
- `role=system`
  - PoC では input 先頭に `user` 相当で含めるか、`instructions` にまとめる。
  - まずは `instructions` に compact task instruction、system messages は input 先頭に `[System context]` として入れる方が無難。

## compact instruction

Codex の prompt に寄せる。

```text
You are performing a CONTEXT CHECKPOINT COMPACTION for Hermes Agent.
Create a handoff summary for another LLM that will resume the task.

Include:
- Current user goal and intent
- Current progress and key decisions made
- Important constraints, preferences, and safety requirements
- Relevant files, commands, APIs, and paths
- What remains to be done as clear next steps
- Critical data, examples, errors, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
Do not invent completed work. Preserve uncertainty and blockers.
```

`focus_topic` がある場合は末尾に追加。

```text
Focus especially on: <focus_topic>
```

## compact API client

`client.py`。

### API key mode

```python
POST https://api.openai.com/v1/responses/compact
Authorization: Bearer <OPENAI_API_KEY>
Content-Type: application/json
```

API key 解決の優先順位 PoC 案。

1. `codex_compact.openai_api_key` が config にあれば使う。ただし secrets を config に置く運用は推奨しない。
2. `OPENAI_API_KEY`
3. Hermes provider config から取れるなら後で対応。

### Codex OAuth mode

Hermes resolver を使う。

```python
from hermes_cli.auth import resolve_codex_runtime_credentials
from agent.auxiliary_client import _codex_cloudflare_headers

creds = resolve_codex_runtime_credentials()
token = creds["api_key"]
base_url = creds["base_url"]  # expected: https://chatgpt.com/backend-api/codex
headers = _codex_cloudflare_headers(token)
headers["Authorization"] = f"Bearer {token}"
headers["Content-Type"] = "application/json"
```

endpoint。

```python
url = base_url.rstrip("/") + "/responses/compact"
```

注意。

- `_codex_cloudflare_headers` は private helper。PoC では使ってよいが、README/AGENTS に private API 依存として書く。
- token は絶対に log しない。
- `~/.hermes/auth.json` / `~/.codex/auth.json` は直接読まない。
- refresh は `resolve_codex_runtime_credentials()` に任せる。

## compact response 抽出

OpenAI API の response shape は検証が必要。PoC では defensive に複数パターンを扱う。

候補。

```python
response["output"]
response["output_text"]
response["choices"]
response["content"]
```

実装方針。

```python
def extract_compact_text(resp):
    if isinstance(resp, dict):
        if resp.get("output_text"):
            return resp["output_text"]
        if resp.get("output"):
            return flatten_response_output(resp["output"])
    raise CompactResponseError("Could not extract compact text")
```

最初の live smoke では `debug_dump: true` にして、token を含まない raw response を plugin-local cache に保存して shape を確認する。ただし compact 対象の会話本文を含むため、default は false。

保存する場合は `.gitignore` する。

```text
.debug/
*.debug.json
```

## replacement history 構築

PoC の返却 history。

```text
[original system messages]
[user message: compact checkpoint summary]
[recent safe tail messages]
```

summary message template。

```text
[Context compacted by hermes-codex-compact]

The following is a compacted checkpoint of prior conversation and tool work.
Treat it as historical context, not as a new user request.
Continue from the current user request using this context.

<checkpoint>
...
</checkpoint>
```

role は `user` を基本にする。Codex local compact も checkpoint summary を user-side context として扱う思想に近いため。

`recent_tail_messages` は初期値 8。tail に tool pair の片割れが入る場合は、該当 pair を丸ごと落とすか丸ごと保持する。

## 最小テスト計画

### `tests/test_conversion.py`

- user message が Responses input に変換される。
- assistant message が Responses input に変換される。
- tool message が text 化される。
- system message が compact context として含まれる。
- list/dict content が落ちずに text 化される。
- long tool result が truncate される。

### `tests/test_message_ops.py`

- `build_replacement_history()` が system + summary + tail を返す。
- summary message role が `user`。
- tail count が設定値以下。
- orphan tool result を作らない。
- tool call の片割れ tail を sanitize できる。

### `tests/test_engine.py`

- `CodexCompactEngine` が `ContextEngine` の instance。
- `name == "codex_compact"`。
- `update_from_response()` が token counters を更新。
- `should_compress()` が threshold を見る。
- client を fake して `compress()` が replacement history を返す。
- client 例外時に元 messages を返す。

### `tests/test_client_payload.py`

- api_key mode の URL / headers が期待通り。
- codex_oauth mode は resolver を mock して URL / headers が期待通り。
- Authorization token を error message に含めない。

## 手動検証計画

### 1. plugin loader smoke

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

### 2. unit tests

```bash
cd ~/.hermes/plugins/hermes-codex-compact
python -m pytest -q
python -m py_compile __init__.py engine.py auth.py client.py conversion.py message_ops.py config.py
```

### 3. API key compact call smoke

小さな fixture messages を使って `client.compact()` を直接呼ぶ。

```bash
OPENAI_API_KEY=... python scripts/smoke_compact.py --auth-mode api_key
```

PoC では script は後から追加してよい。

### 4. Codex OAuth compact call smoke

Hermes の `openai-codex` login 済みを前提にする。

```bash
python scripts/smoke_compact.py --auth-mode codex_oauth
```

401/403/404 が返る可能性がある。その場合は response status / body を token 除去して記録する。

### 5. Hermes manual `/compress`

`~/.hermes/config.yaml` に一時設定。

```yaml
plugins:
  enabled:
    - hermes-codex-compact
context:
  engine: codex_compact
codex_compact:
  auth_mode: api_key
```

CLI で起動し、長めの会話を作って `/compress`。

検証。

- API error で session が壊れない。
- compression 後に次 turn が通る。
- compact summary が履歴に入る。
- token usage が減る。

## 実装ステップ

### Step 1: repo skeleton

作成済みまたは次に作る。

```text
plugin.yaml
__init__.py
engine.py
config.py
client.py
conversion.py
message_ops.py
tests/
.gitignore
README.md
AGENTS.md
```

### Step 2: pure functions から実装

先に外部 API を呼ばない関数を作る。

- `content_to_text()`
- `truncate_text()`
- `prepare_for_compact()`
- `hermes_messages_to_compact_payload()`
- `extract_compact_text()`
- `build_replacement_history()`
- `sanitize_tail_tool_pairs()`

### Step 3: fake client で engine test

実 API なしで `compress()` の基本挙動を固める。

### Step 4: API key client

`urllib.request` か `httpx` を使う。

Hermes runtime の依存に寄せるなら、まず stdlib `urllib.request` で十分。PoC で依存を増やさない。

### Step 5: Codex OAuth client

Hermes resolver import を使う。

- `resolve_codex_runtime_credentials()`
- `_codex_cloudflare_headers()`

private API 依存はコメントに明記。

### Step 6: plugin registration

`register(ctx)` で `ctx.register_context_engine(CodexCompactEngine())`。

plugin discovery smoke を実行。

### Step 7: manual `/compress` smoke

`context.engine: codex_compact` で Hermes CLI から `/compress` を試す。

## リスクと対策

### `responses/compact` の response shape が想定と違う

対策:

- `extract_compact_text()` を defensive にする。
- live smoke で raw shape を確認してから調整する。

### Codex OAuth で `/responses/compact` が通らない

対策:

- PoC では失敗を結果として扱う。
- API key 経路が通れば plugin の価値は残る。
- status code / sanitized body を記録する。

### tool pair が壊れて次 API call が失敗する

対策:

- PoC でも tail sanitizer は入れる。
- summary message + system のみで返す mode も fallback option として持てるようにしておく。

### compact API に送る payload が大きすぎる

対策:

- long tool result truncate。
- PoC では `max_input_chars` / `max_tool_result_chars` を持つ。
- 本格版で token-based trim にする。

### token / secret 漏洩

対策:

- token を log しない。
- exception message から Authorization を redaction。
- debug dump default false。
- `~/.codex/auth.json` は読まない。

### Hermes private API 依存

対策:

- PoC では許容。
- README/AGENTS に明記。
- 実用化時に public helper 化を検討。

## 後回しにする項目

- built-in compressor fallback。
- SQLite checkpoint store。
- context retrieval tool。
- replacement history 永続化。
- Codex風 recent user messages 20k token 保持。
- model downshift compaction。
- mid-turn compaction の special handling。
- prompt caching との詳細調整。
- Slack gateway 長文 thread での運用検証。
- A/B 評価 corpus。

## 完了条件: PoC

- `git status` で plan と skeleton が管理できる状態になる。
- unit tests が通る。
- plugin loader が `hermes-codex-compact` を発見する。
- fake client で `ContextEngine.compress()` が replacement history を返す。
- API key mode の direct compact smoke が通る、または API error が明確に取れる。
- Codex OAuth mode の direct compact smoke が通る、または 401/403/404 等の結果を安全に取得できる。
- manual `/compress` 後に Hermes の次 turn が壊れない。

## PoC 実装結果メモ

2026-04-30 時点で、計画した PoC フェーズは実装済み。

- Phase 1: `conversion.py` / `message_ops.py` と tests を実装。
- Phase 2: `CodexCompactEngine` と fake-client tests を実装。
- Phase 3: OpenAI API key client と payload/header tests を実装。
  - この環境では `OPENAI_API_KEY` が未設定のため、実 API key smoke は `OPENAI_API_KEY is required` で停止することを確認。
- Phase 4: Codex OAuth client と smoke script を実装。
  - `python scripts/smoke_compact.py --auth-mode codex_oauth --model gpt-5.5 --execute` が成功。
  - 小さな fixture に対して compact text と Hermes replacement history を生成できた。
- Phase 5: `plugin.yaml` / `__init__.py` / README / AGENTS を追加。
  - Hermes plugin loader で `found=True`, `enabled=True`, `error=None`, `context_engine_name=codex_compact` を確認。
  - `~/.hermes/config.yaml` には `plugins.enabled: hermes-codex-compact` を追加済み。
  - 安全のため `context.engine` はまだ `compressor` のまま。実際にこの engine を使うには `context.engine: codex_compact` に切り替える。

## 次の判断ポイント

PoC 後に判断する。

1. 実セッションの `/compress` で、Hermes built-in より継続品質が良いか。
2. Codex OAuth 経路を experimental として使い続けるか、OpenAI API key 経路を正式推奨にするか。
3. replacement history に tail をどれだけ残すべきか。
4. fallback / checkpoint / retrieval tool を入れる価値があるか。
5. plugin を公開 repo 化するか、local experimental に留めるか。


## 2026-04-30 addendum: private real-session fixture 到達点

今回の追加到達点:

1. `context.engine` は本番設定では変えず、plugin repo 内のテスト/スクリプトから compact pipeline を直接実行できるようにする。
2. 実セッション履歴は `tests/fixtures/private/` に置き、`.gitignore` で追跡しない。
3. JSONL fixture loader は Hermes session export / message-only JSONL / wrapper object の差異に耐える。
4. `scripts/smoke_compact.py --fixture ...` で実セッションを dry-run / remote execute できる。
5. `--compare-builtin` で Hermes built-in compressor の入力可否または比較不能理由を表示し、PoC段階で A/B の足場を作る。
6. private fixture smoke は `RUN_CODEX_COMPACT_PRIVATE=1` の opt-in にして、通常 pytest では skip する。

完了条件:

- synthetic fixture loader tests が通る。
- private fixture が無い環境でも通常 test suite は通る。
- smoke CLI の dry-run が fixture path と replacement history preview を出す。
- raw compact payload / response / 実履歴はデフォルト保存しない。


## 2026-04-30 investigation: Codex-equivalent conversion / pre-processing

実セッション smoke の結果、`/responses/compact` API は到達可能だが、現在の flattened `{role, content}` 入力では raw history 寄りの出力になり、Hermes built-in compressor より悪かった。改善には次の2層が必要。

### 1. Hermes形式 → OpenAI/Codex Responses形式

Hermes runtime の参考実装:

- `~/.hermes/hermes-agent/agent/codex_responses_adapter.py`
  - `_chat_messages_to_responses_input()` が chat-style Hermes messages を Responses input items に変換している。
  - `system` は input items から除外し、instructions 側へ入る。
  - `user` / `assistant` content list は `input_text` / `output_text` parts に変換する。
  - assistant の `tool_calls` は `type: function_call` item に変換する。
  - tool result は `type: function_call_output` item に変換する。
  - Codex reasoning / message replay metadata がある場合は `reasoning` / exact assistant `message` item として保持する。
  - call_id は deterministic fallback を使い、function_call と function_call_output を対応させる。

現在の plugin の `conversion.py` は tool call/result をテキスト化しているだけなので、まずこの adapter の subset を plugin 側へ移植する。目標は compact payload の `input` を plain chat messages ではなく Codex `ResponseItem` 相当へ近づけること。

### 2. Codex compact実行時と同じ前処理

Codex remote compact の参考実装:

- `/tmp/openai-codex/codex-rs/core/src/tasks/compact.rs`
  - provider が remote compaction 対応なら `compact_remote::run_remote_compact_task()`、そうでなければ local compact。
- `/tmp/openai-codex/codex-rs/core/src/compact_remote.rs`
  - `history = sess.clone_history()`
  - `base_instructions = sess.get_base_instructions()`
  - `trim_function_call_history_to_fit_context_window()` で context window に収まるまで Codex-generated tail items を後ろから削る。
  - `history.for_prompt(input_modalities)` で model-visible prompt input を作る。
  - `built_tools(...).model_visible_specs()` で compact API に渡す tools を構築。
  - `Prompt { input, tools, parallel_tool_calls, base_instructions, personality, output_schema: None, output_schema_strict: true }` を作る。
  - `model_client.compact_conversation_history()` が `responses/compact` に投げる。
  - 返った `ResponseItem[]` は `process_compacted_history()` で developer や非実ユーザー prefix を落とす。
  - mid-turn では initial context を last real user / summary の前に再注入。manual/pre-turn では再注入しない。
- `/tmp/openai-codex/codex-rs/core/src/client.rs`
  - compact payload は `model`, `input`, `instructions`, `tools`, `parallel_tool_calls`, `reasoning`, `text`。
  - `instructions` は `prompt.base_instructions.text`。compact専用 prompt ではなく、通常 turn と同じ base instructions。
- `/tmp/openai-codex/codex-rs/core/src/client_common.rs`
  - `Prompt.get_formatted_input()` は freeform `apply_patch` tool があると shell outputs を structured text に reserialize。
- `/tmp/openai-codex/codex-rs/core/src/compact.rs`
  - local compact は `SUMMARIZATION_PROMPT` を user input として追加し、通常 sampling で summary を作る。
  - replacement history は recent real user messages（最大20k tokens） + summary user message。
  - remote compact は API から返った replacement history を使うが、post-filter と initial-context reinjection は行う。

### 実装方針

1. `responses_conversion.py` を作り、Hermes messages を Codex `ResponseItem` wire shape に近い dict list へ変換する。既存 `agent.codex_responses_adapter._chat_messages_to_responses_input()` の挙動を fixture tests で再現する。
2. compact payload は `instructions` に Codex と同じく base instructions / system prompt 相当を入れる。現在の compact専用 instruction は、local fallback summary 用か optional override に下げる。
3. `tools` は空配列ではなく、Hermes enabled tool schemas を Responses function tool schema に変換して渡す。ただし standalone smoke では fixture metadata から復元できないので、まず empty / provided schemas の2モードにする。
4. `parallel_tool_calls` は model/tool config に従う。fixture smoke では明示 default。
5. context-window fitting は Codex と同じ思想に寄せる: raw input が大きすぎる場合、古いものではなく Codex-generated / tool-heavy tail items から削る。ただし Hermes では live latest user を消さない guard を置く。
6. compact response の post-processing を実装する: developer/system duplication を落とし、実ユーザー message と assistant summary/compaction item を残す。Hermes message history へ戻すときは valid OpenAI chat sequence に変換する。
7. A/B fixture で以下を比較する: original chars/tokens, payload item count, compact_text/replacement chars, tool-output残存率, structured checkpoint項目の有無。

この順序は「1→2」でも「2→1」でもよいが、まず変換 layer を正しくしないと `/responses/compact` の学習済み挙動に乗れない可能性が高い。
