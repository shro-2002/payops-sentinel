"""AG Studio LLM relay: neutral <-> Anthropic mapping, caps, failure modes. The Anthropic client is faked (no network)."""

import base64
import gzip
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import studio
from app.config import get_settings
from app.main import app

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeMessages:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.resp


def _resp(content, stop_reason="end_turn"):
    return SimpleNamespace(id="msg_1", model="claude-opus-5-5", stop_reason=stop_reason, content=content,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


@pytest.fixture()
def fake(monkeypatch):
    s = get_settings()
    saved = (s.operator_token, s.anthropic_api_key)
    s.operator_token, s.anthropic_api_key = TOKEN, "test-key"
    messages = FakeMessages(_resp([SimpleNamespace(type="text", text="hello"),
                                   SimpleNamespace(type="tool_use", id="toolu_9", name="get_finding", input={"a": 1})],
                                  stop_reason="tool_use"))
    monkeypatch.setattr(studio, "_client", lambda key: SimpleNamespace(messages=messages))
    yield messages
    s.operator_token, s.anthropic_api_key = saved


TURN = {
    "system": "be brief",
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "investigate"}]},
        {"role": "assistant", "content": [{"type": "tool_call", "id": "call.1", "name": "get_finding", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_call_id": "call.1", "output": "{\"ok\":1}"}]},
    ],
    "tools": [{"name": "get_finding", "description": "latest finding", "parameters": {"properties": {}}}],
}


def test_requires_operator_token(fake):
    assert TestClient(app).post("/api/v1/studio/llm", json=TURN).status_code == 401


def test_maps_turn_both_ways(fake):
    r = TestClient(app).post("/api/v1/studio/llm", json=TURN, headers=AUTH)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["content"] == [{"type": "text", "text": "hello"},
                               {"type": "tool_call", "id": "toolu_9", "name": "get_finding", "input": {"a": 1}}]
    assert data["stop_reason"] == "tool_use" and data["error"] is None
    sent = fake.calls[0]
    assert "tool_choice" not in sent
    assert sent["output_config"] == {"effort": get_settings().anthropic_effort}
    assert sent["max_tokens"] == 16000 and sent["system"] == "be brief"
    assert sent["tools"][0]["input_schema"]["type"] == "object"
    use, result = sent["messages"][1]["content"][0], sent["messages"][2]["content"][0]
    assert use["type"] == "tool_use" and result["type"] == "tool_result"
    assert use["id"] == result["tool_use_id"] == "call_1"  # sanitised identically on both sides


def test_accepts_gzip_envelope(fake):
    packed = base64.b64encode(gzip.compress(json.dumps(TURN).encode())).decode()
    r = TestClient(app).post("/api/v1/studio/llm", json={"gzip_b64": packed}, headers=AUTH)
    assert r.status_code == 200 and fake.calls


def test_rejects_garbage_envelope(fake):
    r = TestClient(app).post("/api/v1/studio/llm", json={"gzip_b64": "!!notbase64"}, headers=AUTH)
    assert r.status_code == 400 and not fake.calls


def test_caps_message_count(fake):
    body = {**TURN, "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}] * 61}
    assert TestClient(app).post("/api/v1/studio/llm", json=body, headers=AUTH).status_code == 422
    assert not fake.calls


def test_refusal_becomes_error_turn(fake):
    fake.resp = _resp([], stop_reason="refusal")
    data = TestClient(app).post("/api/v1/studio/llm", json=TURN, headers=AUTH).json()["data"]
    assert data["error"]["code"] == "REFUSAL" and data["content"][0]["type"] == "text"


def test_api_error_is_502_without_details(fake):
    fake.exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    r = TestClient(app).post("/api/v1/studio/llm", json=TURN, headers=AUTH)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "LLM_UNAVAILABLE"
    assert "test-key" not in r.text


def test_config_never_exposes_anthropic_key(fake, monkeypatch):
    monkeypatch.setenv("AG_STUDIO_LICENSE_KEY", "lic-123")
    data = TestClient(app).get("/api/v1/studio/config", headers=AUTH).json()["data"]
    assert data["license_key"] == "lic-123" and data["ai_enabled"] is True
    assert "test-key" not in json.dumps(data)
