import importlib.util
from pathlib import Path


class FakePluginContext:
    def __init__(self):
        self.engines = []

    def register_context_engine(self, engine):
        self.engines.append(engine)


def load_plugin_module():
    path = Path(__file__).resolve().parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_codex_compact_plugin", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_register_adds_codex_compact_context_engine():
    plugin = load_plugin_module()
    ctx = FakePluginContext()

    plugin.register(ctx)

    assert len(ctx.engines) == 1
    assert ctx.engines[0].name == "codex_compact"
