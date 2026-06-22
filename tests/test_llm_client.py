import pytest
from agent_archive.llm import complete, LLMError

class FakeTransport:
    """记录每次请求体，按预设依次返回 (status, body)。"""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def __call__(self, url, headers, body):
        self.calls.append(body)
        status, payload = self.responses.pop(0)
        return status, payload

def _ok(content):
    return {"choices": [{"message": {"content": content}}]}

def test_complete_returns_content():
    t = FakeTransport([(200, _ok('{"x":1}'))])
    out = complete("sys", "user", base_url="http://x/v1", api_key="k", model="m", transport=t)
    assert out == '{"x":1}'
    assert '"response_format"' in t.calls[0]

def test_complete_downgrades_on_400_response_format():
    t = FakeTransport([(400, {"error": "response_format unsupported"}), (200, _ok('{"x":2}'))])
    out = complete("sys", "user", base_url="http://x/v1", api_key="k", model="m", transport=t)
    assert out == '{"x":2}'
    assert '"response_format"' in t.calls[0]
    assert '"response_format"' not in t.calls[1]

def test_complete_raises_on_persistent_error():
    t = FakeTransport([(500, {}), (500, {}), (500, {}), (500, {}), (500, {})])
    with pytest.raises(LLMError):
        complete("s", "u", base_url="http://x/v1", api_key="k", model="m",
                 transport=t, max_retries=2, backoff=0)

def test_complete_rejects_non_ascii_key_clearly_before_send():
    t = FakeTransport([(200, _ok('{"x":1}'))])
    with pytest.raises(LLMError) as ei:
        complete("s", "u", base_url="http://x/v1", api_key="ＳＫ-bad", model="m", transport=t)
    assert "ASCII" in str(ei.value)
    assert t.calls == []          # 校验在发请求前，绝不外发

def test_complete_strips_whitespace_in_key():
    t = FakeTransport([(200, _ok('{"x":1}'))])
    out = complete("s", "u", base_url="http://x/v1", api_key="  sk-clean\n", model="m", transport=t)
    assert out == '{"x":1}'
