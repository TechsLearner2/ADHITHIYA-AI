"""Tests for the provider layer (core.llm) — Groq/OpenAI routing. No network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import llm


def test_provider_defaults_to_groq(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {})
    assert llm.provider() == "groq"
    assert llm.chat_model() == "llama-3.3-70b-versatile"
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
