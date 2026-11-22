"""Provider routing tests (Groq/OpenAI/gateway/local). No network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import llm


def test_provider_has_no_implicit_cloud_default(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {})
    assert llm.provider() == "unconfigured"
    assert llm.chat_model() == ""
    assert llm.stt_model() == ""
    assert llm._chat_models() == []
    with pytest.raises(RuntimeError, match="No AI provider key is configured"):
        llm._client()


def test_provider_explicit_openai(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "openai"})
    assert llm.provider() == "openai"
    assert llm.chat_model() == "gpt-4o-mini"
    assert llm.stt_model() == "whisper-1"


def test_provider_autodetects_unique_provider_key(monkeypatch):
    for config, expected in (
        ({"groq_api_key": "gsk-test"}, "groq"),
        ({"openai_api_key": "sk-test"}, "openai"),
        ({"gateway_api_key": "gateway-test"}, "gateway"),
    ):
        monkeypatch.setattr(llm, "_cfg", lambda cfg=config: cfg)
        assert llm.provider() == expected


def test_provider_flags_multiple_keys_as_ambiguous(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "groq_api_key": "gsk-test", "gateway_api_key": "gateway-test",
    })
    assert llm.provider() == "ambiguous"
    with pytest.raises(RuntimeError, match="More than one provider key"):
        llm._client()


def test_provider_and_key_are_inferred_from_generic_api_key(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"api_key": "sk-or-v1-test"})
    assert llm.provider() == "gateway"
    assert llm.get_api_key() == "sk-or-v1-test"
    assert llm.chat_model() == "openrouter/auto"
    monkeypatch.setattr(llm, "_cfg", lambda: {"api_key": "opaque-token"})
    assert llm.provider() == "unknown"
    with pytest.raises(RuntimeError, match="does not identify a provider"):
        llm._client()


def test_auto_provider_infers_key_prefix_or_gateway_url():
    assert llm.infer_provider_from_api_key("gsk_test") == "groq"
    assert llm.infer_provider_from_api_key("sk-or-v1-test") == "gateway"
    assert llm.infer_provider_from_api_key("sk-test") == "openai"
    assert llm.infer_provider_from_api_key(
        "custom-token", "https://my-gateway.example/v1") == "gateway"
    assert llm.infer_provider_from_api_key("custom-token") is None


def test_api_key_prefers_active_provider(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "groq", "groq_api_key": "gsk-a", "openai_api_key": "sk-b",
    })
    assert llm.get_api_key() == "gsk-a"
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "openai", "groq_api_key": "gsk-a", "openai_api_key": "sk-b",
    })
    assert llm.get_api_key() == "sk-b"
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "gateway", "gateway_api_key": "gateway-test",
        "openai_api_key": "sk-b", "groq_api_key": "gsk-a",
    })
    assert llm.get_api_key() == "gateway-test"


def test_gateway_provider_defaults_and_overrides(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "gateway"})
    assert llm.provider() == "gateway"
    assert llm.chat_model() == "openrouter/auto"
    assert llm.gateway_base_url() == "https://openrouter.ai/api/v1"
    assert llm._chat_models() == ["openrouter/auto"]

    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "gateway", "gateway_model": "vendor/model-x",
        "gateway_base_url": "https://gateway.example/v1/",
    })
    assert llm.chat_model() == "vendor/model-x"
    assert llm.gateway_base_url() == "https://gateway.example/v1"


def test_gateway_key_autodetects_or_requires_choice_when_multiple(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"gateway_api_key": "gateway-test"})
    assert llm.provider() == "gateway"
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "gateway_api_key": "gateway-test", "groq_api_key": "gsk-a",
    })
    assert llm.provider() == "ambiguous"


def test_gateway_url_alias_and_validation(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "gateway", "gateway_url": "http://localhost:8080/v1/",
    })
    assert llm.gateway_base_url() == "http://localhost:8080/v1"
    for invalid in ("", "ftp://gateway.example/v1", "https://", "https://user:pass@gateway.example/v1"):
        with pytest.raises(ValueError, match="Invalid gateway_base_url"):
            llm.validate_gateway_base_url(invalid)


def test_gateway_client_uses_its_key_and_configured_url(monkeypatch):
    config = {
        "provider": "gateway", "gateway_api_key": "gateway-test",
        "gateway_base_url": "https://gateway.example/openai/v1/",
    }
    captured = {}

    class _OpenAIStub:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "_cfg", lambda: config)
    monkeypatch.setattr(llm, "_OpenAI", _OpenAIStub)
    llm._client()
    assert captured["api_key"] == "gateway-test"
    assert captured["base_url"] == "https://gateway.example/openai/v1"


def test_gateway_client_requires_its_own_api_key(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "gateway", "openai_api_key": "must-not-be-used",
    })
    with pytest.raises(RuntimeError, match="gateway_api_key is missing"):
        llm._client()


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


def test_chunk_text_splits_at_limit():
    text = "One two three four five six seven eight nine ten " * 6
    for chunk in llm._chunk_text(text, 200):
        assert len(chunk) <= 200
    assert " ".join(llm._chunk_text(text, 200)) == " ".join(text.split())


def test_chunk_text_short_untouched():
    assert llm._chunk_text("hello world", 200) == ["hello world"]


def test_concat_wavs_joins_two():
    import io
    import wave

    def mk_wav(samples):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(samples)
        return buf.getvalue()

    a = mk_wav(b"\x00\x00\x01\x00")
    b = mk_wav(b"\x02\x00\x03\x00")
    joined = llm._concat_wavs([a, b])
    with wave.open(io.BytesIO(joined), "rb") as w:
        assert w.getnframes() == 4


def test_tool_schemas_stay_under_groq_budget():
    """Regression guard: the full tool list must stay small enough for Groq's
    free-tier ~8k tokens/min budget (was ~8.7k tokens before compaction)."""
    import json
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "main.py"
    text = src.read_text(encoding="utf-8")
    m = re.search(r"TOOL_DECLARATIONS = \[(.*?)\n\]", text, re.S)
    assert m, "TOOL_DECLARATIONS not found"
    ns = {}
    exec("TOOL_DECLARATIONS = [" + m.group(1) + "\n]", ns)
    core_decls = ns["TOOL_DECLARATIONS"]

    from core.plugin_loader import discover_plugins
    core_names = {t["name"] for t in core_decls}
    reg = discover_plugins(plugins_dir=Path(__file__).resolve().parent.parent / "plugins",
                           core_tool_names=core_names, logger=lambda m: None, extra_dirs=[])
    tools = llm.to_openai_tools(core_decls + reg.get_tool_declarations())
    total_chars = len(json.dumps(tools))
    # ~55k chars would be ~8.7k tokens; we keep well under that now.
    assert total_chars < 30000, f"tool schemas bloated: {total_chars} chars"

    # Parameter descriptions must be dropped (that's what kept us under budget).
    for t in tools:
        for prop in t["function"]["parameters"].get("properties", {}).values():
            assert "description" not in prop, f"param description leaked on {t['function']['name']}"


def test_local_provider_no_key_needed(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "local"})
    assert llm.provider() == "local"
    assert llm.get_api_key() == "ollama"
    assert llm.chat_model() == "qwen3:8b"


def test_local_chat_models_prefer_installed(monkeypatch):
    # Desired model first, then the best of what's actually pulled.
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "local"})
    monkeypatch.setattr(llm, "_local_installed_models",
                        lambda: ["llama3.2", "qwen2.5:7b"])
    assert llm._chat_models() == [
        "qwen3:8b", "qwen2.5:7b", "llama3.2", "qwen3:4b",
    ]


def test_local_chat_models_desired_installed_first(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "local"})
    monkeypatch.setattr(llm, "_local_installed_models",
                        lambda: ["qwen3:8b", "llama3.2"])
    assert llm._chat_models()[0] == "qwen3:8b"


def test_local_model_override(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "local", "local_model": "llama3.2"})
    assert llm.chat_model() == "llama3.2"


def test_local_image_gen_refused(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "local"})
    with pytest.raises(RuntimeError):
        llm.generate_image("a cat")


def test_local_vision_polite(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "local"})
    out = llm.chat_with_image("what do you see?", b"\x89PNGfake")
    assert "no vision model" in out


class _ToolsErr(Exception):
    pass


def test_chat_retries_without_tools_when_unsupported(monkeypatch):
    calls = []

    def create(kwargs):
        calls.append(kwargs)
        if kwargs.get("tools"):
            raise _ToolsErr("model does not support tools")
        return _Resp(_Msg(content="plain reply"))

    class _C:
        def __init__(self, fn):
            self.completions = _Completions(fn)
        def __getattr__(self, name):  # audio/… not used here
            return None

    class _Cl:
        def __init__(self, fn):
            self.chat = _C(fn)

    monkeypatch.setattr(llm, "_client", lambda: _Cl(create))
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "openai"})

    out = llm.chat(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "x", "parameters": {"type": "object", "properties": {}}}}],
    )
    assert out["text"] == "plain reply"
    assert len(calls) == 2
    assert "tools" not in calls[1]




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
    assert tried == ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"]


def test_gateway_chat_sends_configured_model(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "gateway", "gateway_api_key": "gateway-test",
        "gateway_model": "provider/model-id",
        "gateway_chat_fallbacks": "fallback/model-a, fallback/model-b",
    })
    assert llm._chat_models() == [
        "provider/model-id", "fallback/model-a", "fallback/model-b",
    ]
    monkeypatch.setattr(llm, "_client", lambda: _Client(
        lambda kwargs: (calls.append(kwargs) or _Resp(_Msg(content="gateway reply")))))

    result = llm.chat([{"role": "user", "content": "hello"}])
    assert result["text"] == "gateway reply"
    assert calls[0]["model"] == "provider/model-id"


def test_gateway_chat_advances_to_configured_fallback(monkeypatch):
    tried = []
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "gateway", "gateway_api_key": "gateway-test",
        "gateway_model": "retired/model",
        "gateway_chat_fallbacks": "working/model",
    })

    def complete(kwargs):
        tried.append(kwargs["model"])
        if kwargs["model"] == "retired/model":
            raise _NotFound("model_not_found")
        return _Resp(_Msg(content="fallback reply"))

    monkeypatch.setattr(llm, "_client", lambda: _Client(complete))
    result = llm.chat([{"role": "user", "content": "hello"}])
    assert result["text"] == "fallback reply"
    assert tried == ["retired/model", "working/model"]


def test_gateway_auto_model_failure_has_configuration_hint(monkeypatch):
    class _MissingModel(Exception):
        status_code = 404

    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "gateway", "gateway_api_key": "gateway-test",
    })

    def fail(_kwargs):
        raise _MissingModel("model_not_found")

    monkeypatch.setattr(llm, "_client", lambda: _Client(fail))
    with pytest.raises(RuntimeError, match="gateway_model"):
        llm.chat([{"role": "user", "content": "hello"}])

