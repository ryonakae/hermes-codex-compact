from engine import CodexCompactEngine


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response or {
            "output": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "compact summary"}]}
            ]
        }
        self.error = error
        self.payloads = []

    def compact(self, payload):
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.response


def test_engine_uses_codex_like_payload_and_structured_response():
    client = FakeClient()
    engine = CodexCompactEngine(client=client, recent_tail_messages=0)

    result = engine.compress([
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"},
    ])

    assert client.payloads[0]["instructions"] == "rules"
    assert client.payloads[0]["input"][0]["type"] == "message"
    assert client.payloads[0]["tools"] == []
    assert result == [{"role": "user", "content": "compact summary"}]
    assert engine.compression_count == 1


def test_engine_text_response_fallback_keeps_recent_tail():
    client = FakeClient({"output_text": "fallback summary"})
    engine = CodexCompactEngine(client=client, recent_tail_messages=1)

    result = engine.compress([
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "latest"},
    ])

    assert "fallback summary" in result[0]["content"]
    assert result[-1] == {"role": "user", "content": "latest"}


def test_engine_returns_original_messages_on_client_error():
    original = [{"role": "user", "content": "hello"}]
    engine = CodexCompactEngine(client=FakeClient(error=RuntimeError("boom")))

    result = engine.compress(original)

    assert result is original
    assert "boom" in engine.last_error
