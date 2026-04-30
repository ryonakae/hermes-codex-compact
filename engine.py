"""ContextEngine implementation for hermes-codex-compact."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from agent.context_engine import ContextEngine
except Exception:  # pragma: no cover - allows local unit tests outside Hermes repo path.
    class ContextEngine:  # type: ignore[no-redef]
        last_prompt_tokens: int = 0
        last_completion_tokens: int = 0
        last_total_tokens: int = 0
        threshold_tokens: int = 0
        context_length: int = 0
        compression_count: int = 0
        threshold_percent: float = 0.75
        protect_first_n: int = 3
        protect_last_n: int = 6

        def update_model(self, model: str = "", context_length: int = 0, **_: Any) -> None:
            self.context_length = context_length
            self.threshold_tokens = int(context_length * self.threshold_percent)

try:
    from .compact_postprocess import compact_response_to_hermes_messages
    from .compact_preprocess import build_codex_compact_payload
    from .config import CodexCompactConfig, load_config
except ImportError:  # pragma: no cover - local test fallback
    from compact_postprocess import compact_response_to_hermes_messages
    from compact_preprocess import build_codex_compact_payload
    from config import CodexCompactConfig, load_config


class CodexCompactEngine(ContextEngine):
    """Experimental remote compact ContextEngine."""

    def __init__(
        self,
        *,
        config: Optional[CodexCompactConfig] = None,
        client: Any = None,
        threshold: Optional[float] = None,
        recent_tail_messages: Optional[int] = None,
    ) -> None:
        self.config = config or load_config()
        if threshold is not None:
            self.config.threshold = float(threshold)
        if recent_tail_messages is not None:
            self.config.recent_tail_messages = int(recent_tail_messages)
        self.model = self.config.model
        self.threshold_percent = float(self.config.threshold)
        self.protect_last_n = int(self.config.recent_tail_messages)
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.threshold_tokens = 0
        self.context_length = 0
        self.compression_count = 0
        self.last_error = ""
        self._client = client

    @property
    def name(self) -> str:
        return "codex_compact"

    def _client_or_default(self) -> Any:
        if self._client is None:
            try:
                from .client import CompactClient
            except ImportError:  # pragma: no cover - local test fallback
                from client import CompactClient

            self._client = CompactClient(self.config)
        return self._client

    def update_model(
        self,
        model: str = "",
        context_length: int = 0,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
    ) -> None:
        if context_length:
            self.context_length = int(context_length)
            self.threshold_tokens = int(self.context_length * self.threshold_percent)

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        usage = usage or {}
        self.last_prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        self.last_completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total = usage.get("total_tokens")
        if total is None:
            total = self.last_prompt_tokens + self.last_completion_tokens
        self.last_total_tokens = int(total or 0)

    def should_compress(self, prompt_tokens: int = None) -> bool:
        tokens = int(prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens)
        return bool(self.threshold_tokens and tokens > self.threshold_tokens)

    def has_content_to_compress(self, messages: List[Dict[str, Any]]) -> bool:
        return len(messages or []) > 2

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> List[Dict[str, Any]]:
        try:
            payload, _stats = build_codex_compact_payload(
                messages,
                model=self.model,
                tools=[],
                parallel_tool_calls=False,
                max_tool_output_chars=self.config.max_tool_result_chars,
                token_budget_chars=self.config.max_input_item_chars,
            )
            response = self._client_or_default().compact(payload)
            replacement = compact_response_to_hermes_messages(
                response,
                messages,
                recent_tail_messages=self.config.recent_tail_messages,
            )
            self.compression_count += 1
            self.last_error = ""
            return replacement
        except Exception as exc:  # PoC safety: never destroy live history on compact failure.
            self.last_error = str(exc)
            return messages

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status() if hasattr(super(), "get_status") else {}
        status.update({"engine": self.name, "last_error": self.last_error})
        return status
