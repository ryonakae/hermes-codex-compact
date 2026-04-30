from engine import CodexCompactEngine


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response or {"output_text": "fake compact summary"}
        self.error = error
        self.payloads = []

    def compact(self, payload):
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.response


def test_engine_identity_and_model_update():
    engine = CodexCompactEngine(client=FakeClient())

    assert engine.name == "codex_compact"
    engine.update_model(model="main", context_length=1000)
    assert engine.context_length == 1000
    assert engine.threshold_tokens == 850


def test_engine_updates_usage_and_should_compress():
    engine = CodexCompactEngine(client=FakeClient(), threshold=0.5)
    engine.update_model(model="main", context_length=1000)

    engine.update_from_response({"prompt_tokens": 400, "completion_tokens": 25, "total_tokens": 425})
    assert engine.last_prompt_tokens == 400
    assert engine.last_completion_tokens == 25
    assert engine.last_total_tokens == 425
    assert engine.should_compress() is False
    assert engine.should_compress(501) is True


def test_engine_compress_uses_client_and_returns_replacement_history():
    client = FakeClient({"output_text": "The task is to build a plugin."})
    engine = CodexCompactEngine(client=client, recent_tail_messages=1)

    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "old"},
        {"role": "user", "content": "latest"},
    ]
    result = engine.compress(messages, current_tokens=900, focus_topic="client")

    assert client.payloads
    assert client.payloads[0]["model"] == engine.model
    assert client.payloads[0]["instructions"] == "rules"
    assert client.payloads[0]["input"][0]["type"] == "message"
    assert "The task is to build a plugin." in result[0]["content"]
    assert result[-1]["content"] == "latest"
    assert engine.compression_count == 1


def test_engine_compress_returns_original_messages_on_client_error():
    messages = [{"role": "user", "content": "do not lose me"}]
    engine = CodexCompactEngine(client=FakeClient(error=RuntimeError("boom")))

    result = engine.compress(messages)

    assert result == messages
    assert "boom" in engine.last_error
