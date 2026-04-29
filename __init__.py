"""Hermes standalone plugin entrypoint for hermes-codex-compact."""

try:
    from .engine import CodexCompactEngine
except ImportError:  # pragma: no cover - plugin loader/test fallback when root is on sys.path.
    from engine import CodexCompactEngine


def register(ctx):
    """Register the experimental ContextEngine with Hermes."""
    ctx.register_context_engine(CodexCompactEngine())


__all__ = ["register", "CodexCompactEngine"]
