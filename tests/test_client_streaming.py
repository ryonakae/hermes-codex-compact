from client import post_json


class FakeResponse:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def test_post_json_parses_responses_sse_output_text(monkeypatch):
    body = '\n'.join([
        'data: {"type":"response.output_text.delta","delta":"hello"}',
        'data: {"type":"response.output_text.delta","delta":" world"}',
        'data: {"type":"response.completed","response":{"id":"resp_1","output":[]}}',
        'data: [DONE]',
        '',
    ])

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse(body))

    parsed = post_json("https://example.test/responses", {"stream": True}, {}, 1)

    assert parsed["id"] == "resp_1"
    assert parsed["output_text"] == "hello world"
