"""Tests for the provider layer (core.llm) — Groq/OpenAI routing. No network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import llm


def test_provider_defaults_to_groq(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {})
    assert llm.provider() == "groq"
    assert llm.chat_model() == "openai/gpt-oss-120b"
    assert llm.stt_model() == "whisper-large-v3-turbo"


def test_provider_explicit_openai(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "openai"})
    assert llm.provider() == "openai"
    assert llm.chat_model() == "gpt-4o-mini"
    assert llm.stt_model() == "whisper-1"


def test_provider_autodetect_openai_key(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"openai_api_key": "sk-test"})
    assert llm.provider() == "openai"


def test_api_key_prefers_active_provider(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "groq", "groq_api_key": "gsk-a", "openai_api_key": "sk-b",
    })
    assert llm.get_api_key() == "gsk-a"
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "openai", "groq_api_key": "gsk-a", "openai_api_key": "sk-b",
    })
    assert llm.get_api_key() == "sk-b"


def test_chat_model_override_wins(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "groq", "chat_model": "custom"})
    assert llm.chat_model() == "custom"


def test_image_guard_on_groq(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "groq"})
    with pytest.raises(RuntimeError):
        llm.generate_image("a cat")


def test_vision_unavailable_on_groq(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "groq"})
    out = llm.chat_with_image("what do you see?", b"\x89PNGfake")
    assert "can't look at images" in out


class _NotFound(Exception):
    status_code = 404


class _Msg:
    def __init__(self, content="hello", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message):
        self.message = message


class _Resp:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _Completions:
    def __init__(self, fn):
        self._fn = fn

    def create(self, **kwargs):
        return self._fn(kwargs)


class _Chat:
    def __init__(self, fn):
        self.completions = _Completions(fn)


class _Client:
    def __init__(self, fn):
        self.chat = _Chat(fn)


def test_chat_falls_back_when_model_retired(monkeypatch):
    tried = []

    def create(kwargs):
        tried.append(kwargs["model"])
        if kwargs["model"] == "openai/gpt-oss-120b":
            raise _NotFound("model_not_found")
        return _Resp(_Msg(content="hi there"))

    monkeypatch.setattr(llm, "_client", lambda: _Client(create))
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "groq"})

    out = llm.chat([{"role": "user", "content": "hi"}])
    assert out["text"] == "hi there"
    assert tried == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]

