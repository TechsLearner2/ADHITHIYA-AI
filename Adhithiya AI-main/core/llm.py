"""LLM provider layer — the single door to the AI brain.

Every AI call in ADHITHIYA goes through here. Providers share one interface;
when no provider is explicitly configured, a single saved API key identifies
the provider. No cloud provider is silently selected when there is no key.

    provider = "groq"   (selected explicitly or inferred from groq_api_key)
        chat   → openai/gpt-oss-120b (free) → gpt-oss-20b / kimi-k2 fallbacks
        STT    → whisper-large-v3-turbo    (free tier)
        TTS    → canopylabs/orpheus-v1-english (free) → OS voice fallback
        vision → qwen/qwen3.6-27b (preview; polite message if unavailable)
        image  → not available on Groq (image generation needs OpenAI)

    provider = "openai" (paid)
        chat  → gpt-4o-mini · STT → whisper-1 · TTS → gpt-4o-mini-tts
        image → gpt-image-1 (falls back to dall-e-3)

    provider = "local" (free forever, private, offline — runs on your computer)
        chat  → Ollama (default qwen3:8b; change via "local_model")
        TTS   → the operating system's built-in voice
        STT   → local faster-whisper if installed, else your free Groq key
        image → not available offline (needs the paid OpenAI provider)

    provider = "builtin" (the built-in brain — no key, no Ollama, no bill)
        chat  → a real neural net that lives on this machine: llama.cpp's
                llama-server + a small open-weight GGUF (Qwen2.5, Apache-2.0),
                downloaded ONCE (~2 GB) into ~/.adhithiya/brain/ and then
                runs forever offline. Zero keys, zero accounts, zero cost.
        TTS   → the operating system's built-in voice
        STT   → local faster-whisper if installed, else your free Groq key
        image → not available offline (needs the paid OpenAI provider)

    provider = "gateway" (any OpenAI-compatible API endpoint)
        chat  → configured gateway URL, key, and model
        URL   → gateway_base_url (defaults to OpenRouter's /api/v1 endpoint)
        model → gateway_model (defaults to "openrouter/auto")

Config (config/api_keys.json):
    provider         — optional explicit selection; otherwise inferred from one saved API key
    groq_api_key     — free key from console.groq.com        (provider=groq)
    openai_api_key   — key from platform.openai.com          (provider=openai)
    gateway_api_key  — key for the configured compatible endpoint (provider=gateway)
    gateway_base_url — OpenAI-compatible API base URL (e.g. https://openrouter.ai/api/v1)
    gateway_model    — optional model ID (default "openrouter/auto")
    gateway_chat_fallbacks — optional comma-separated fallback model IDs
    chat_model       — optional override (per-provider default otherwise)
    stt_model        — optional override
    say_voice        — macOS `say` voice used as the Groq speech fallback (e.g. "Samantha")
    groq_tts_voice   — Groq Orpheus voice (e.g. "troy", "autumn", "hannah"); default "troy"
    tts_voice        — OpenAI speaking voice (provider=openai), default "alloy"
    image_model      — OpenAI image model (default "gpt-image-1")
    temperature      — optional, default 0.7
    local_keep_alive — how long Ollama keeps the model in RAM after pre-warm
                       (default "30m"; e.g. "2h") — beats the 5-minute eviction
    local_no_think   — true → append Qwen3's /no_think switch: no internal
                       monologue, several× faster replies on CPU-only Macs

    Built-in brain (provider="builtin") — see core/builtin_brain.py for the
    full installer/lifecycle; config keys:
        builtin_profile      — tiny | fast | balanced (default) | strong
        builtin_model_url    — custom GGUF URL instead of a profile
        builtin_engine_version — llama.cpp build pin (default "b10839")
        builtin_port         — localhost port (default 18771)
        builtin_ctx_size     — context tokens (default 8192)
        builtin_gpu_layers   — GPU offload layers (Apple Silicon: 99; default 0)
        builtin_hybrid       — auto-power routing: when a groq_api_key is
                               saved, heavy turns go to Groq's free cloud brain
                               and the local brain answers the rest (default:
                               auto — long/complex prompts only). Set false for
                               strictly-local/private, true for always-cloud.
"""

from __future__ import annotations

import base64
import json
import platform
import re

from memory.config_manager import load_api_keys

# Imported once here, on the main thread, so later calls from mic/worker/dashboard
# threads never race on the package's submodule import locks (which previously
# caused "deadlock detected by _ModuleLock('openai.resources.chat')").
try:
    from openai import OpenAI as _OpenAI
except Exception:  # noqa: BLE001 — openai is optional at import time (tests stub _client)
    _OpenAI = None

# The built-in brain (llama-server + GGUF model) is implemented in its own
# stdlib-only module; here we only borrow its identity constants so this file
# stays the single door every provider walks through.
try:
    from core.builtin_brain import BUILTIN_MODEL
except Exception:  # noqa: BLE001 — import-time safety (never expected)
    BUILTIN_MODEL = "adhithiya-brain"

# ── defaults ──────────────────────────────────────────────────────────────────

DEFAULT_CHAT_MODEL   = "gpt-4o-mini"
DEFAULT_TTS_MODEL    = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE    = "alloy"
DEFAULT_STT_MODEL    = "whisper-1"
DEFAULT_IMAGE_MODEL  = "gpt-image-1"
IMAGE_FALLBACK       = "dall-e-3"
TTS_FALLBACK         = "tts-1"

UNCONFIGURED_PROVIDER = "unconfigured"
AMBIGUOUS_PROVIDER = "ambiguous"
UNKNOWN_PROVIDER = "unknown"
DEFAULT_GATEWAY_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_GATEWAY_CHAT_MODEL = "openrouter/auto"
GROQ_BASE_URL        = "https://api.groq.com/openai/v1"
# Groq retired the free Llama 3.x models (moved to "Enterprise"); the current
# free chat models are the GPT-OSS family and Kimi K2. We keep an ordered
# fallback list and auto-advance on "model_not_found", so a Groq retirement can
# never brick the assistant again.
GROQ_CHAT_MODEL      = "openai/gpt-oss-120b"
GROQ_CHAT_FALLBACKS  = [
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
    "moonshotai/kimi-k2-instruct",
    "minimaxai/minimax-m2.7",
    "groq/compound-mini",
]
GROQ_STT_MODEL       = "whisper-large-v3-turbo"
GROQ_STT_FALLBACKS   = ["whisper-large-v3"]
GROQ_TTS_MODEL       = "canopylabs/orpheus-v1-english"
GROQ_TTS_VOICE       = "troy"   # troy | autumn | hannah | austin | …
GROQ_VISION_MODEL    = "qwen/qwen3.6-27b"
GROQ_VISION_FALLBACK = "qwen/qwen3.8-27b"

LOCAL_BASE_URL       = "http://localhost:11434/v1"   # Ollama's OpenAI-compatible endpoint
LOCAL_CHAT_MODEL     = "qwen3:8b"                    # best 2026 tool-calling brain in the 8B class; override via config
LOCAL_CHAT_FALLBACKS = ["qwen3:4b", "llama3.2"]      # lighter models, tried if the default isn't pulled
LOCAL_WHISPER_MODEL  = "base"                        # faster-whisper model (tiny/base/small/…)
# Preferred brains for Intel Macs, best first — used to order whatever the
# user has actually pulled (lower index = picked first).
_LOCAL_PREFERENCE    = [
    "qwen3:14b", "qwen3:8b", "qwen2.5:7b", "llama3.1:8b",
    "qwen3:4b", "gemma3:4b", "phi3:mini", "llama3.2", "phi4-mini",
]


def _ollama_health() -> tuple[bool, list[str]]:
    """(is Ollama reachable?, [pulled model names]) — best-effort 2s probe."""
    import json as _json
    from urllib import request as _req
    try:
        with _req.urlopen("http://localhost:11434/api/tags", timeout=2.0) as r:
            data = _json.loads(r.read().decode("utf-8"))
        names = [str(m.get("name", "")).strip() for m in data.get("models", [])
                 if str(m.get("name", "")).strip()]
        return True, names
    except Exception:
        return False, []


# How long a pre-warmed model stays in RAM. Ollama's 5-minute default evicts
# the brain after every coffee break, forcing a ~90s cold load (measured on an
# Intel MacBook Pro, qwen3:8b) onto the next question — which reads as
# "Ollama isn't answering". 30 minutes matches a working session; override
# via the "local_keep_alive" config key (e.g. "2h", "45m").
_LOCAL_KEEP_ALIVE = "30m"


def _prewarm_payload() -> dict:
    """Body for the keep-alive warm-up POST (see prewarm_local)."""
    return {"model": chat_model(), "prompt": "", "keep_alive": _keep_alive()}


def _keep_alive() -> str:
    return model("local_keep_alive") or _LOCAL_KEEP_ALIVE


_LOCAL_BUSY = 0   # >0 while a local (Ollama) request or model load is in flight


def _mark_local_busy(delta: int) -> None:
    global _LOCAL_BUSY
    _LOCAL_BUSY = max(0, _LOCAL_BUSY + delta)


def local_busy() -> bool:
    """True while a local chat request or pre-warm is running.

    On CPU-only Macs that work legitimately pins the CPU at ~100% for the
    whole reply — callers like the system monitor stand down instead of
    telling the user to "close heavy apps" (the heavy app is the brain)."""
    return _LOCAL_BUSY > 0


def prewarm_local() -> bool:
    """Load the local brain into RAM now (background thread) and ask Ollama
    to keep it resident for the keep-alive window.

    The empty prompt generates nothing — the call's real job is the load plus
    the long keep_alive, so the FIRST question after launch (and after any
    idle break) skips the cold-load tax. Best-effort: never raises, never
    blocks startup. Returns True if a warm-up was started, False when not in
    local mode.
    """
    if provider() != "local":
        return False
    import threading
    from urllib import request as _req

    def _warm():
        url = "http://localhost:11434/api/generate"
        body = json.dumps(_prewarm_payload()).encode("utf-8")
        req = _req.Request(url, data=body, headers={"Content-Type": "application/json"})
        _mark_local_busy(1)
        try:
            # The load itself can take minutes on CPU-only Macs; this thread
            # is a daemon, so however long it takes, startup is never blocked.
            with _req.urlopen(req, timeout=300.0) as r:
                r.read()
            print(f"[LLM] Local model {chat_model()!r} is warm "
                  f"(kept for {_keep_alive()}).")
        except Exception as e:  # noqa: BLE001 — warming is best-effort
            print(f"[LLM] Local pre-warm skipped: {e}")
        finally:
            _mark_local_busy(-1)

    threading.Thread(target=_warm, daemon=True, name="ollama-prewarm").start()
    return True


def _local_installed_models() -> list[str]:
    """Models currently pulled in Ollama (GET /api/tags). [] if Ollama is off."""
    return _ollama_health()[1]

_CONFIG_CACHE: dict = {"ts": 0.0, "cfg": {}}
_ORPHEUS_DISABLED: bool = False   # set once Orpheus rejects us (terms/plan)


def _cfg():
    try:
        return load_api_keys()
    except Exception:
        return {}


def get_api_key() -> str:
    """Return the active provider's key (or a local-mode placeholder)."""
    data = _cfg()
    p = provider()
    if p == "builtin":
        return "builtin"
    if p == "local":
        return "ollama"
    if p == "gateway":
        key = data.get("gateway_api_key") or data.get("api_key")
    elif p == "groq":
        key = data.get("groq_api_key") or data.get("api_key")
    elif p == "openai":
        key = data.get("openai_api_key") or data.get("api_key")
    else:
        return ""
    return str(key or "").strip()


def model(name: str) -> str:
    return str(_cfg().get(name, "") or "").strip()


def validate_gateway_base_url(value: str) -> str:
    """Normalize and validate an OpenAI-compatible HTTP(S) base URL."""
    from urllib.parse import urlsplit

    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        valid = (parsed.scheme.lower() in {"http", "https"}
                 and bool(parsed.hostname) and not parsed.username
                 and not parsed.password and not parsed.fragment
                 and (parsed.port is None or 1 <= parsed.port <= 65535)
                 and not any(ch.isspace() for ch in raw))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "Invalid gateway_base_url. Enter an OpenAI-compatible HTTP(S) "
            "base URL, for example https://openrouter.ai/api/v1."
        )
    return raw


def gateway_base_url() -> str:
    """Return the configured OpenAI-compatible gateway base URL.

    ``gateway_url`` is also accepted as an older/shorter config spelling.
    A public OpenRouter endpoint is the default; self-hosted gateways can use
    HTTP as long as the URL has a hostname (for example localhost).
    """
    data = _cfg()
    raw = (data.get("gateway_base_url") or data.get("gateway_url")
           or DEFAULT_GATEWAY_BASE_URL)
    return validate_gateway_base_url(str(raw))


def infer_provider_from_api_key(api_key: str, gateway_url: str = "") -> str | None:
    """Infer common provider keys; return None when the key is ambiguous.

    Named provider fields in api_keys.json are more reliable and are used by
    ``provider()`` first. This helper is for setup's single-key auto mode.
    """
    key = str(api_key or "").strip().lower()
    if not key:
        return None
    if key.startswith(("gsk_", "gsk-")):
        return "groq"
    if key.startswith(("sk-or-", "or-v1-")):
        return "gateway"
    url = str(gateway_url or "").strip().rstrip("/")
    if url and url != DEFAULT_GATEWAY_BASE_URL.rstrip("/"):
        return "gateway"
    if key.startswith("sk-"):
        return "openai"
    return None


def provider() -> str:
    """Active backend: explicit provider, or the provider represented by one key.

    Returns ``unconfigured`` when no key/provider is saved and ``ambiguous``
    when several provider keys exist without an explicit provider selection.
    """
    data = _cfg()
    p = str(data.get("provider") or "").strip().lower()
    if p in {"groq", "openai", "gateway", "local", "builtin"}:
        return p

    key_fields = (
        ("groq", "groq_api_key"),
        ("openai", "openai_api_key"),
        ("gateway", "gateway_api_key"),
    )
    configured = [name for name, field in key_fields
                  if str(data.get(field) or "").strip()]
    if len(configured) == 1:
        return configured[0]
    if len(configured) > 1:
        return AMBIGUOUS_PROVIDER

    generic_key = str(data.get("api_key") or "").strip()
    if generic_key:
        return (infer_provider_from_api_key(
            generic_key, data.get("gateway_base_url") or data.get("gateway_url"))
                or UNKNOWN_PROVIDER)
    return UNCONFIGURED_PROVIDER


def chat_model() -> str:
    p = provider()
    if p in {UNCONFIGURED_PROVIDER, AMBIGUOUS_PROVIDER, UNKNOWN_PROVIDER}:
        return ""
    if p == "gateway":
        return model("gateway_model") or DEFAULT_GATEWAY_CHAT_MODEL
    override = model("chat_model")
    if override:
        return override
    if p == "groq":
        return GROQ_CHAT_MODEL
    if p == "local":
        return model("local_model") or LOCAL_CHAT_MODEL
    if p == "builtin":
        return BUILTIN_MODEL
    return DEFAULT_CHAT_MODEL


def tts_model() -> str:
    return model("tts_model") or DEFAULT_TTS_MODEL


def tts_voice() -> str:
    return model("tts_voice") or DEFAULT_TTS_VOICE


def stt_model() -> str:
    override = model("stt_model")
    if override:
        return override
    p = provider()
    if p in {UNCONFIGURED_PROVIDER, AMBIGUOUS_PROVIDER, UNKNOWN_PROVIDER}:
        return ""
    return GROQ_STT_MODEL if p == "groq" else DEFAULT_STT_MODEL


def image_model() -> str:
    return model("image_model") or DEFAULT_IMAGE_MODEL


def temperature() -> float:
    try:
        return float(_cfg().get("temperature", 0.7))
    except (TypeError, ValueError):
        return 0.7


def _model_unavailable(err: Exception) -> bool:
    """True if the provider rejected the model id — retired, not on this plan,
    no access, or a billing/quota wall. In any of these cases it's worth trying
    the next candidate model instead of failing the whole turn."""
    code = getattr(err, "status_code", None) or getattr(err, "code", None)
    if code in (401, 402, 403, 404, 413, 429):
        return True
    text = str(err).lower()
    return any(k in text for k in (
        "model_not_found", "does not exist", "no longer",
        "not allowed", "no access", "access denied", "quota",
        "insufficient", "balance", "billing", "not available", "unavailable",
        "rate_limit", "too large", "terms",
    ))


def _chat_models() -> list[str]:
    """Ordered chat-model candidates for the active provider (first valid wins)."""
    p = provider()
    if p in {UNCONFIGURED_PROVIDER, AMBIGUOUS_PROVIDER, UNKNOWN_PROVIDER}:
        return []
    if p == "groq":
        out = [chat_model()]
        for m in GROQ_CHAT_FALLBACKS:
            if m not in out:
                out.append(m)
        return out
    if p == "local":
        desired = chat_model()
        installed = _local_installed_models()
        # Desired brain first, then the best of what's actually pulled, then
        # the remaining fallbacks (which 404 fast if not pulled). This way the
        # user's downloaded model always wins — no config editing needed.
        ranked = sorted(
            [m for m in installed if m != desired],
            key=lambda m: _LOCAL_PREFERENCE.index(m) if m in _LOCAL_PREFERENCE else 999,
        )
        out = [desired] + ranked
        for m in LOCAL_CHAT_FALLBACKS:
            if m not in out:
                out.append(m)
        return out
    if p == "gateway":
        out = [chat_model()]
        for candidate in model("gateway_chat_fallbacks").split(","):
            candidate = candidate.strip()
            if candidate and candidate not in out:
                out.append(candidate)
        return out
    if p == "builtin":
        return [chat_model()]   # one brain, one model — no fallback list
    return [chat_model()]


def _stt_models() -> list[str]:
    """Ordered STT-model candidates for the active provider."""
    if provider() != "groq":
        return [stt_model()]
    out = [stt_model()]
    for m in GROQ_STT_FALLBACKS:
        if m not in out:
            out.append(m)
    return out


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_think(text: str) -> str:
    """Remove inline qwen3-style <think>…</think> monologue from a reply."""
    return _THINK_RE.sub("", text).strip()


def _no_think_enabled() -> bool:
    """Config switch: skip the local model's internal monologue entirely
    ("local_no_think": true) — the right default for CPU-only Macs where
    every thinking token is seconds of waiting."""
    return str(_cfg().get("local_no_think", "")).strip().lower() in ("1", "true", "yes", "on")


def _local_no_think_messages(messages: list[dict]) -> list[dict]:
    """Append Qwen3's documented `/no_think` soft switch when running local
    with local_no_think enabled. Prefers the system prompt; falls back to the
    last user message. Returns a new list — the caller's messages are never
    mutated (the dashboard/memory may hold the same dicts)."""
    if provider() != "local" or not _no_think_enabled():
        return messages
    # /no_think is a Qwen3 soft switch — other models (phi3, llama, …) don't
    # produce <think> blocks and would just read it as prompt noise.
    if "qwen" not in str(chat_model()).lower():
        return messages
    msgs = list(messages)
    idx = next((i for i, m in enumerate(msgs) if m.get("role") == "system"), None)
    if idx is None:
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") == "user":
                idx = i
                break
    if idx is None:
        return msgs
    patched = dict(msgs[idx])
    patched["content"] = ((patched.get("content") or "") + " /no_think").strip()
    msgs[idx] = patched
    return msgs


def _tools_unsupported(err: Exception) -> bool:
    """True if the model rejected the `tools` parameter (some local models
    don't support function calling). We then retry the turn without tools."""
    t = str(err).lower()
    return any(k in t for k in (
        "does not support tools", "tools not supported", "tools are not",
        "unknown parameter", "unexpected keyword", "function calling",
    ))


def _local_unreachable(err: Exception) -> bool:
    """True if Ollama simply isn't answering (app closed, model still loading)."""
    text = (type(err).__name__ + " " + str(err)).lower()
    return any(k in text for k in ("timeout", "connection", "connect", "refused"))


def _client():
    p = provider()
    if p == UNCONFIGURED_PROVIDER:
        raise RuntimeError(
            "No AI provider key is configured. Enter one in setup or add a "
            "provider-specific key to `~/.adhithiya/config/api_keys.json`."
        )
    if p == AMBIGUOUS_PROVIDER:
        raise RuntimeError(
            "More than one provider key is configured. Set `provider` in "
            "`~/.adhithiya/config/api_keys.json` or keep only the key to use."
        )
    if p == UNKNOWN_PROVIDER:
        raise RuntimeError(
            "The saved `api_key` format does not identify a provider. Set "
            "`provider` in `~/.adhithiya/config/api_keys.json` or choose one "
            "in setup."
        )
    api_key = get_api_key()
    if p in {"groq", "openai", "gateway"} and not api_key:
        field = {"groq": "groq_api_key", "openai": "openai_api_key",
                 "gateway": "gateway_api_key"}[p]
        raise RuntimeError(
            f"Provider {p!r} is selected, but {field} is missing from "
            "`~/.adhithiya/config/api_keys.json`."
        )
    cls = _OpenAI
    if cls is None:
        from openai import OpenAI as cls
    kwargs = {"api_key": api_key, "max_retries": 2, "timeout": 60.0}
    if p == "groq":
        kwargs["base_url"] = GROQ_BASE_URL
    elif p == "gateway":
        kwargs["base_url"] = gateway_base_url()
    elif p == "builtin":
        # llama-server's OpenAI-compatible door; ensure_server raises the
        # helpful "install the brain" error when it isn't up yet.
        from core import builtin_brain
        builtin_brain.ensure_server()
        kwargs["base_url"] = f"http://127.0.0.1:{builtin_brain.server_port()}/v1"
        kwargs["timeout"] = 300.0   # cold CPU loads can take a minute+
    elif p == "local":
        kwargs["base_url"] = LOCAL_BASE_URL
        # Cold-loading a 7–8B model into RAM on an Intel Mac can take well over
        # a minute; a 60s timeout would abort the very first request every
        # time, which looked exactly like a hang in the startup briefing.
        kwargs["timeout"] = 300.0
    return cls(**kwargs)


# ── chat ──────────────────────────────────────────────────────────────────────

def _builtin_chat(messages: list[dict], tools: list[dict] | None = None,
                  max_tokens: int | None = None,
                  temp: float | None = None) -> dict:
    """Chat through the built-in brain (llama-server on localhost).

    Mirrors the shape of chat() → {"text": …, "tool_calls": […]}. Most of the
    work is making failures human: not-installed-yet, server died, or the
    request itself — each gets an actionable message instead of a stack trace.
    """
    from core import builtin_brain

    # Auto-power: heavy turns go to the free cloud brain when a Groq key is
    # saved; the local brain stays the fallback (and handles everything when
    # the machine is offline or the user sets "builtin_hybrid": false).
    if _hybrid_cloud_requested(messages):
        try:
            out = _groq_turn(messages, tools, max_tokens, temp)
            print("[LLM] Cloud brain answered (auto-power hybrid).")
            return out
        except Exception as e:  # noqa: BLE001
            print(f"[LLM] Cloud brain unavailable ({e}) — falling back to "
                  "the local built-in brain.")
    try:
        builtin_brain.ensure_server()
    except RuntimeError:
        raise                                # already actionable
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"The built-in brain couldn't start ({e}). Run "
            "`python3 -m core.builtin_brain restart` and try again.") from e

    client = _client()   # provider is "builtin" → localhost base URL
    if max_tokens is None:
        max_tokens = builtin_brain.max_tokens()   # configurable cap
    _mark_local_busy(1)
    last_err: Exception | None = None
    # Passes: with tools, then (rarely) without when the model glitches on the
    # tool schema; the last pass retries a bare conversation once.
    tries = 3
    for attempt in range(tries):
        use_tools = bool(tools) and attempt != 1
        try:
            kwargs: dict = {
                "model": chat_model(),
                "messages": messages,
                "temperature": temperature() if temp is None else temp,
                "max_tokens": max_tokens or builtin_brain.max_tokens(),
            }
            if use_tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            text = str(e).lower()
            if ("connection" in text or "refused" in text or "reset" in text):
                # Server died mid-turn (OOM, crash…) — bring it back for next time.
                builtin_brain.stop_server()
                raise RuntimeError(
                    "The built-in brain stopped mid-answer (it may have run "
                    "out of memory). It has been restarted for next time — "
                    "try again, or pick a smaller model profile in config "
                    "('builtin_profile': tiny/fast) if this repeats.") from e
            if "model_not_found" in text or "unknown model" in text:
                raise RuntimeError(
                    "The brain doesn't recognise its model name — restart it "
                    "with `python3 -m core.builtin_brain restart`.") from e
            if attempt < tries - 1:
                continue
            raise RuntimeError(
                f"The built-in brain failed this request ({e}). "
                "Check `~/.adhithiya/brain/server.log` for details.") from e
        finally:
            _mark_local_busy(-1)

        result = _completion_to_result(resp)
        if result.get("text") or result.get("tool_calls"):
            return result
        # Empty reply: give the brain one plain re-ask before giving up.
        if attempt < tries - 1:
            continue
    print(f"[LLM] Built-in brain returned nothing after {tries} tries.")
    return {"text": "", "tool_calls": []}


def _completion_to_result(resp) -> dict:
    """Normalise an OpenAI-style completion into {"text", "tool_calls"}."""
    msg = resp.choices[0].message
    tool_calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except (json.JSONDecodeError, TypeError):
            args = {}
        tool_calls.append({
            "id": tc.id,
            "name": tc.function.name,
            "arguments": args,
        })
    text = (msg.content or "").strip()
    # Thinking models (qwen3 etc.) can leave `content` empty and put the real
    # answer in `reasoning_content` — never hand back silence.
    text = _strip_think(text)
    if not text and not tool_calls:
        rc = getattr(msg, "reasoning_content", None)
        if not rc:
            rc = (getattr(msg, "model_extra", None) or {}).get("reasoning_content")
        if rc:
            text = str(rc).strip()
    return {"text": text, "tool_calls": tool_calls}


# ── builtin ↔ cloud hybrid routing (auto-power) ──────────────────────────────

# Heavy requests deserve a bigger brain than a small local model can offer.
# When a Groq key is saved, the builtin provider can hand such turns to the
# free cloud brain and fall back to the local brain if the cloud is offline.
_CLOUD_KEYWORDS = (
    "summar", "explain", "analy", "essay", "detailed", "research",
    "compare and", "write a", "write an", "review", "translate",
    "debug", "outline", "comprehensive", "in depth", "in-depth",
    "step by step", "alternatives", "pros and cons", "report",
)
_CLOUD_MIN_LEN  = 60     # keywords only count on substantial prompts
_CLOUD_AUTO_LEN = 140    # anything longer than this → cloud (hybrid auto)


def _hybrid_cloud_requested(messages: list[dict]) -> bool:
    """Should the builtin provider hand this turn to the cloud brain?

    Requires provider == 'builtin' AND a saved groq_api_key. The
    "builtin_hybrid" config flag sets the policy:
      false/off   → never (fully local & private)
      true/on     → always (cloud first, local fallback)
      unset (auto) → only long turns, or substantial turns with a heavy
                     keyword (summarize/explain/compare/write…)
    """
    if provider() != "builtin":
        return False
    key = str(_cfg().get("groq_api_key") or "").strip()
    if not key:
        return False
    flag = str(_cfg().get("builtin_hybrid") or "").strip().lower()
    if flag in ("false", "0", "no", "off"):
        return False
    text = ""
    for m in reversed(messages or []):
        c = m.get("content")
        if isinstance(c, str) and c.strip():
            text = c.strip()
            break
    if flag in ("true", "1", "yes", "on"):
        return True
    if len(text) >= _CLOUD_AUTO_LEN:
        return True
    low = text.lower()
    return len(text) >= _CLOUD_MIN_LEN and any(k in low for k in _CLOUD_KEYWORDS)


def _groq_turn(messages: list[dict], tools: list[dict] | None = None,
               max_tokens: int | None = None,
               temp: float | None = None) -> dict:
    """One chat turn against Groq's free models — the hybrid partner of the
    builtin brain. Same shape as chat(). Raises on failure (the caller then
    falls back to the local brain)."""
    key = str(_cfg().get("groq_api_key") or "").strip()
    if not key:
        raise RuntimeError("Hybrid mode has no Groq key saved.")
    cls = _OpenAI
    if cls is None:
        from openai import OpenAI as cls
    client = cls(api_key=key, base_url=GROQ_BASE_URL,
                 max_retries=1, timeout=90.0)
    last_err: Exception | None = None
    for model_id in _groq_models():
        for use_tools in ([True, False] if tools else [True]):
            kwargs: dict = {
                "model": model_id,
                "messages": messages,
                "temperature": temperature() if temp is None else temp,
            }
            if use_tools and tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if _model_unavailable(e):
                    print(f"[LLM] Cloud model {model_id!r} unavailable — next…")
                    break
                if use_tools and _tools_unsupported(e):
                    continue
                raise
            return _completion_to_result(resp)
    raise RuntimeError(last_err or RuntimeError("no cloud model available"))


def _groq_models() -> list[str]:
    """Ordered Groq chat candidates: preferred default first, then fallbacks."""
    out = [GROQ_CHAT_MODEL]
    for m in GROQ_CHAT_FALLBACKS:
        if m not in out:
            out.append(m)
    return out


def chat(messages: list[dict], tools: list[dict] | None = None,
         max_tokens: int | None = None, temp: float | None = None) -> dict:
    """Send messages and return {"text": str, "tool_calls": [...]}.

    messages: OpenAI chat format (role: system/user/assistant/tool).
    tools:    OpenAI tool format (type:"function" ...).
    """
    if provider() == "builtin":
        return _builtin_chat(messages, tools, max_tokens, temp)
    client = _client()
    last_err: Exception | None = None
    # First pass sends tools; if the model can't do function calling we retry
    # without them so plain conversation still works.
    passes = [True] if not tools else [True, False]
    for model_id in _chat_models():
        for use_tools in passes:
            kwargs: dict = {
                "model": model_id,
                "messages": _local_no_think_messages(messages),
                "temperature": temperature() if temp is None else temp,
            }
            if use_tools and tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            _local_req = provider() == "local"
            if _local_req:
                _mark_local_busy(1)
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if _model_unavailable(e):
                    print(f"[LLM] Model {model_id!r} unavailable — trying next…")
                    break   # next model
                if use_tools and _tools_unsupported(e):
                    print(f"[LLM] Model {model_id!r} can't use tools — retrying without.")
                    continue  # next pass (no tools)
                if provider() == "local" and _local_unreachable(e):
                    detail = f"{type(e).__name__}: {str(e)[:160]}"
                    print(f"[LLM] Local chat failed — {detail}")
                    raise RuntimeError(
                        "Ollama isn't answering (" + detail + "). Make sure "
                        "the Ollama app is open and a model is pulled (e.g. "
                        "`ollama pull qwen3:8b`). If Ollama just restarted or "
                        "is still loading, give it a minute and try again."
                    ) from e
                raise
            finally:
                if _local_req:
                    _mark_local_busy(-1)

            return _completion_to_result(resp)

    if provider() == "local" and last_err is not None:
        raise RuntimeError(
            "Couldn't reach a local model. Make sure the Ollama app is running, "
            "then pull a brain in Terminal, e.g.: `ollama pull qwen3:8b` "
            "(if you interrupted a pull, just re-run it — it resumes). "
            "Last error: " + str(last_err)[:200]
        )
    if (provider() == "gateway"
            and chat_model() == DEFAULT_GATEWAY_CHAT_MODEL
            and last_err is not None):
        code = getattr(last_err, "status_code", None) or getattr(last_err, "code", None)
        detail = str(last_err).lower()
        if code == 404 or any(marker in detail for marker in (
                "model_not_found", "no endpoints found", "unknown model",
                "model does not exist", "no models available")):
            raise RuntimeError(
                "The gateway did not accept the default model "
                f"{DEFAULT_GATEWAY_CHAT_MODEL!r}. Add a `gateway_model` entry "
                "to `~/.adhithiya/config/api_keys.json` with a model ID "
                "supported by your gateway."
            ) from last_err
    raise (last_err or RuntimeError("no chat model available"))


def chat_with_image(prompt: str, image_bytes: bytes, mime: str = "image/png") -> str:
    """Ask a vision-capable model about an image. Returns its text answer."""
    if provider() in ("local", "builtin"):
        if provider() == "builtin":
            return ("The built-in brain is text-only (Qwen2.5). Switch provider "
                    "to Groq or OpenAI in config/api_keys.json if you want "
                    "screen/camera understanding.")
        return ("This setup runs fully offline and has no vision model yet. "
                "Pull a vision model in Ollama (e.g. `ollama pull llava`) if you "
                "want screen/camera understanding.")
    if provider() == "groq":
        try:
            return _groq_vision(prompt, image_bytes, mime)
        except Exception as e:  # noqa: BLE001
            print(f"[Vision] Groq vision unavailable: {e}")
            return ("I can't look at images right now — the free vision model is "
                    "unavailable on this plan. Screen/camera vision will work once "
                    "a vision model is accessible (or with provider='openai').")
    b64 = base64.b64encode(image_bytes).decode("ascii")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]
    return chat([{"role": "user", "content": content}])["text"]


def generate_content(contents):
    """Compatibility helper mirroring the legacy ``generate_content(contents)``.

    Accepts a str (text prompt) or a list mixing str prompts and image objects
    (PIL Image, raw bytes, or an object with .data/.mime_type). Returns an
    object with a ``.text`` attribute.
    """
    from types import SimpleNamespace

    if isinstance(contents, str):
        return SimpleNamespace(text=chat([{"role": "user", "content": contents}])["text"])

    if isinstance(contents, (list, tuple)):
        text_parts: list[str] = []
        image: bytes | None = None
        mime = "image/png"
        for item in contents:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if image is None:
                image, mime = _coerce_image(item)
        prompt = "\n".join(p for p in text_parts if p.strip())
        if image is not None:
            return SimpleNamespace(text=chat_with_image(prompt or "Describe this image.", image, mime))
        return SimpleNamespace(text=chat([{"role": "user", "content": prompt}])["text"])

    raise TypeError("generate_content expects a str or a list")


def _coerce_image(item) -> tuple[bytes, str]:
    """Normalise an image object to (bytes, mime)."""
    # object with .data / .mime_type (our compat Part)
    if hasattr(item, "data") and hasattr(item, "mime_type"):
        return bytes(item.data), str(item.mime_type or "image/png")
    # dict form
    if isinstance(item, dict):
        if item.get("data"):
            return bytes(item["data"]), str(item.get("mime_type") or "image/png")
    # raw bytes
    if isinstance(item, (bytes, bytearray)):
        b = bytes(item)
        mime = "image/jpeg" if b[:2] == b"\xff\xd8" else "image/png"
        return b, mime
    # PIL Image
    if hasattr(item, "save"):
        import io
        buf = io.BytesIO()
        try:
            item.save(buf, format="PNG")
        except Exception:
            item.save(buf, format="JPEG")
        return buf.getvalue(), "image/png"
    raise TypeError(f"unsupported image object: {type(item)}")


# ── speech-to-text ────────────────────────────────────────────────────────────

_FW_CACHE: dict = {}


def _fw_model():
    """Load (and cache) the local faster-whisper model. Downloads on first use."""
    import faster_whisper
    name = model("whisper_local_model") or LOCAL_WHISPER_MODEL
    m = _FW_CACHE.get(name)
    if m is None:
        m = faster_whisper.WhisperModel(name, device="cpu", compute_type="int8")
        _FW_CACHE[name] = m
    return m


def _transcribe_local(wav_bytes: bytes) -> str:
    """STT for provider in ('local','builtin'): local faster-whisper first,
    then the user's free Groq key (hybrid), so hearing works even without an
    offline whisper install."""
    import io

    # 1) fully-local whisper (if the optional package is installed)
    try:
        import faster_whisper  # noqa: F401
        have_local = True
    except Exception:
        have_local = False
    if have_local:
        try:
            segs, _info = _fw_model().transcribe(io.BytesIO(wav_bytes))
            text = " ".join(seg.text for seg in segs).strip()
            if text:
                return text
        except Exception as e:  # noqa: BLE001
            print(f"[STT] Local whisper failed ({e}) — using Groq fallback.")

    # 2) hybrid fallback: free Groq Whisper (only if a groq_api_key exists)
    groq_key = str(_cfg().get("groq_api_key") or "").strip()
    if groq_key:
        cls = _OpenAI
        if cls is None:
            from openai import OpenAI as cls
        client = cls(api_key=groq_key, base_url=GROQ_BASE_URL,
                     max_retries=2, timeout=60.0)
        resp = client.audio.transcriptions.create(
            model=GROQ_STT_MODEL,
            file=("audio.wav", wav_bytes, "audio/wav"),
        )
        return (resp.text or "").strip()

    raise RuntimeError(
        "No speech-to-text available. Add your free Groq key to "
        "config/api_keys.json as groq_api_key, or install faster-whisper "
        "in the app's Python environment. On macOS 12, use Python 3.12 "
        "because newer onnxruntime builds may not support that OS."
    )


def transcribe_wav(wav_bytes: bytes) -> str:
    """Transcribe a WAV audio blob with Whisper. Returns text ('' on failure)."""
    if provider() in ("local", "builtin"):
        return _transcribe_local(wav_bytes)
    client = _client()
    last_err: Exception | None = None
    for model_id in _stt_models():
        try:
            resp = client.audio.transcriptions.create(
                model=model_id,
                file=("audio.wav", wav_bytes, "audio/wav"),
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            if _model_unavailable(e):
                print(f"[LLM] STT model {model_id!r} unavailable — trying next…")
                continue
            raise
        return (resp.text or "").strip()
    raise (last_err or RuntimeError("no STT model available"))


# ── text-to-speech ────────────────────────────────────────────────────────────

def tts_wav(text: str) -> bytes:
    """Synthesise text as a WAV file (PCM). Raises on failure."""
    global _ORPHEUS_DISABLED
    if provider() in ("local", "builtin"):
        return _say_tts(text)
    if provider() == "groq":
        if not _ORPHEUS_DISABLED:
            try:
                return _orpheus_tts(text)
            except Exception as e:  # noqa: BLE001
                if "terms" in str(e).lower():
                    _ORPHEUS_DISABLED = True
                    print("[TTS] Orpheus needs one-time terms acceptance at "
                          "console.groq.com — using the system voice for now.")
                else:
                    print(f"[TTS] Orpheus failed ({e}); falling back to the system voice.")
        return _say_tts(text)
    client = _client()
    try:
        resp = client.audio.speech.create(
            model=tts_model(),
            voice=tts_voice(),
            input=text,
            response_format="wav",
        )
    except Exception:
        resp = client.audio.speech.create(
            model=TTS_FALLBACK,
            voice=tts_voice(),
            input=text,
            response_format="wav",
        )
    data = getattr(resp, "content", None)
    if data is None:
        data = resp.read()
    return bytes(data)


def _chunk_text(text: str, limit: int = 200) -> list[str]:
    """Split text into <=limit-char pieces on sentence/word boundaries
    (Groq's Orpheus TTS caps input at 200 chars per call)."""
    import re
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    cur = ""
    for sent in sentences:
        while len(sent) > limit:
            cut = sent[:limit]
            sp = cut.rfind(" ")
            cut = cut[:sp] if sp > 0 else cut
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(cut.strip())
            sent = sent[len(cut):].strip()
        if len(cur) + len(sent) + 1 <= limit:
            cur = f"{cur} {sent}".strip()
        else:
            if cur:
                chunks.append(cur)
            cur = sent
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c]


def _concat_wavs(wavs: list[bytes]) -> bytes:
    """Concatenate WAV blobs (same format) into a single WAV."""
    import io
    import wave
    if not wavs:
        raise ValueError("no audio")
    if len(wavs) == 1:
        return wavs[0]
    frames: list[bytes] = []
    params = None
    for w in wavs:
        with wave.open(io.BytesIO(w), "rb") as f:
            if params is None:
                params = f.getparams()
            frames.append(f.readframes(f.getnframes()))
    out = io.BytesIO()
    with wave.open(out, "wb") as f:
        f.setparams(params)
        for fr in frames:
            f.writeframes(fr)
    return out.getvalue()


def _orpheus_tts(text: str) -> bytes:
    """Groq Orpheus TTS → WAV bytes (200-char chunks stitched together)."""
    client = _client()
    voice = model("groq_tts_voice") or GROQ_TTS_VOICE
    wavs: list[bytes] = []
    for chunk in _chunk_text(text, 200):
        resp = client.audio.speech.create(
            model=GROQ_TTS_MODEL,
            voice=voice,
            input=chunk,
            response_format="wav",
        )
        data = getattr(resp, "content", None)
        if data is None:
            data = resp.read()
        wavs.append(bytes(data))
    return _concat_wavs(wavs)


def _groq_vision(prompt: str, image_bytes: bytes, mime: str = "image/png") -> str:
    """Groq Qwen vision model → text description. Raises on failure."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]
    client = _client()
    last_err: Exception | None = None
    for model_id in (GROQ_VISION_MODEL, GROQ_VISION_FALLBACK):
        try:
            resp = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": content}],
                temperature=0.3,
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            if _model_unavailable(e):
                continue
            raise
        msg = resp.choices[0].message
        return (msg.content or "").strip()
    raise (last_err or RuntimeError("Groq vision unavailable"))


def _say_tts(text: str) -> bytes:
    """Use the native system speech engine and return its output as WAV bytes."""
    if platform.system() == "Windows":
        return _windows_sapi_tts(text)
    if platform.system() == "Darwin":
        return _mac_say_tts(text)
    raise RuntimeError("Native offline speech is supported on Windows and macOS.")


def _windows_sapi_tts(text: str) -> bytes:
    """Use Windows' built-in SAPI voice via System.Speech (no extra package)."""
    import subprocess
    import tempfile
    from pathlib import Path

    script = (
        "param([string]$OutputPath, [string]$TextPath)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "Add-Type -AssemblyName System.Speech\n"
        "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "try {\n"
        "  $text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)\n"
        "  $synth.SetOutputToWaveFile($OutputPath)\n"
        "  $synth.Speak($text)\n"
        "} finally { $synth.Dispose() }\n"
    )
    with tempfile.TemporaryDirectory(prefix="adhithiya-tts-") as temp_dir:
        root = Path(temp_dir)
        script_path = root / "speak.ps1"
        text_path = root / "text.txt"
        wav_path = root / "speech.wav"
        script_path.write_text(script, encoding="utf-8")
        text_path.write_text(text, encoding="utf-8")
        try:
            subprocess.run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(script_path),
                 str(wav_path), str(text_path)],
                check=True, capture_output=True, timeout=90,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Windows PowerShell was not found for system speech.") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Windows system speech timed out.") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or exc.stdout or b"SAPI failed"
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", "replace")
            raise RuntimeError(f"Windows system speech failed: {detail.strip()[-300:]}") from exc
        if not wav_path.is_file() or wav_path.stat().st_size <= 44:
            raise RuntimeError("Windows system speech did not produce a WAV file.")
        return wav_path.read_bytes()


def _mac_say_tts(text: str) -> bytes:
    """macOS built-in `say` voice → WAV bytes (free, offline)."""
    import os
    import subprocess
    import tempfile

    voice = model("say_voice")
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "out.wav")
        aiff = os.path.join(d, "out.aiff")

        # Preferred: straight to WAV (macOS honours --file-format/--data-format).
        cmd = ["say", "-o", wav, "--file-format=WAVE", "--data-format=LEI16@24000"]
        if voice:
            cmd = ["say", "-v", voice, "-o", wav, "--file-format=WAVE", "--data-format=LEI16@24000"]
        cmd.append(text)
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            if os.path.getsize(wav) > 44:
                with open(wav, "rb") as f:
                    return f.read()
        except Exception:
            pass

        # Fallback: write AIFF, then convert with afconvert.
        try:
            subprocess.run(["say", "-o", aiff, text], check=True, capture_output=True, timeout=60)
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@24000", aiff, wav],
                check=True, capture_output=True, timeout=60,
            )
            if os.path.getsize(wav) > 44:
                with open(wav, "rb") as f:
                    return f.read()
        except Exception:
            pass

    raise RuntimeError("macOS 'say' text-to-speech failed.")


# ── image generation ──────────────────────────────────────────────────────────

def generate_image(prompt: str) -> bytes:
    """Generate an image and return its raw bytes (PNG). Raises on failure."""
    if provider() in ("local", "builtin"):
        raise RuntimeError(
            "Image generation isn't available offline. It needs the paid "
            "OpenAI provider (set config provider to 'openai')."
        )
    if provider() == "groq":
        raise RuntimeError(
            "Image generation isn't available on the free Groq provider. "
            "Set config provider to 'openai' (paid) to generate images."
        )
    client = _client()
    last_error = None
    for name in (image_model(), IMAGE_FALLBACK):
        try:
            resp = client.images.generate(model=name, prompt=prompt,
                                          size="1024x1024", n=1)
            item = resp.data[0] if resp.data else None
            if item is None:
                last_error = "no image returned"
                continue
            if getattr(item, "b64_json", None):
                return base64.b64decode(item.b64_json)
            if getattr(item, "url", None):
                import requests
                return requests.get(item.url, timeout=60).content
            last_error = "image data missing"
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
    raise RuntimeError(last_error or "image generation failed")


# ── tool-schema conversion (legacy declarations → OpenAI tools) ───────────────

_TYPE_MAP = {
    "STRING": "string",
    "INTEGER": "integer",
    "NUMBER": "number",
    "BOOLEAN": "boolean",
    "OBJECT": "object",
    "ARRAY": "array",
}


def _clip(text: str, limit: int) -> str:
    """Truncate long descriptions — keeps schemas small enough for the free
    Groq tier's per-request token budget without losing the callable meaning."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _convert_schema(schema: dict) -> dict:
    out = {}
    t = schema.get("type")
    if t:
        mapped = _TYPE_MAP.get(str(t).upper(), str(t).lower())
        out["type"] = mapped
    # Parameter descriptions are intentionally NOT emitted: the 46 tools'
    # JSON schemas alone were ~8.7k tokens (over Groq's free 8k/min budget).
    # The tool-level description + parameter NAMES carry the calling info.
    props = schema.get("properties")
    if isinstance(props, dict):
        out["properties"] = {k: _convert_schema(v) for k, v in props.items()}
    items = schema.get("items")
    if isinstance(items, dict):
        out["items"] = _convert_schema(items)
    req = schema.get("required")
    if isinstance(req, list):
        out["required"] = req
    enums = schema.get("enum")
    if isinstance(enums, list):
        out["enum"] = enums
    return out


def to_openai_tools(declarations: list[dict]) -> list[dict]:
    """Convert legacy-style function declarations to OpenAI tool objects."""
    tools = []
    for decl in declarations:
        params = decl.get("parameters") or {"type": "OBJECT", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name": decl.get("name", ""),
                "description": _clip(decl.get("description", ""), 160),
                "parameters": _convert_schema(params),
            },
        })
    return tools
