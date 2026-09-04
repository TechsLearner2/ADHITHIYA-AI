"""LLM provider layer — the single door to the AI brain.

Every AI call in ADHITHIYA goes through here. Two providers sit behind one
interface; switching is a one-line config change, never a code rewrite.

    provider = "groq"   (default — FREE, no credit card)
        chat   → openai/gpt-oss-120b (free) → gpt-oss-20b / kimi-k2 fallbacks
        STT    → whisper-large-v3-turbo    (free tier)
        TTS    → canopylabs/orpheus-v1-english (free) → Mac `say` fallback
        vision → qwen/qwen3.6-27b (preview; polite message if unavailable)
        image  → not available on Groq (image generation needs OpenAI)

    provider = "openai" (paid)
        chat  → gpt-4o-mini · STT → whisper-1 · TTS → gpt-4o-mini-tts
        image → gpt-image-1 (falls back to dall-e-3)

Config (config/api_keys.json):
    provider         — "groq" (default) or "openai"
    groq_api_key     — free key from console.groq.com        (provider=groq)
    openai_api_key   — key from platform.openai.com          (provider=openai)
    chat_model       — optional override (per-provider default otherwise)
    stt_model        — optional override
    say_voice        — macOS voice used as the Groq speech FALLBACK (e.g. "Samantha")
    groq_tts_voice   — Groq Orpheus voice (e.g. "troy", "autumn", "hannah"); default "troy"
    tts_voice        — OpenAI speaking voice (provider=openai), default "alloy"
    image_model      — OpenAI image model (default "gpt-image-1")
    temperature      — optional, default 0.7
"""

from __future__ import annotations

import base64
import json

from memory.config_manager import load_api_keys

# ── defaults ──────────────────────────────────────────────────────────────────

DEFAULT_CHAT_MODEL   = "gpt-4o-mini"
DEFAULT_TTS_MODEL    = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE    = "alloy"
DEFAULT_STT_MODEL    = "whisper-1"
DEFAULT_IMAGE_MODEL  = "gpt-image-1"
IMAGE_FALLBACK       = "dall-e-3"
TTS_FALLBACK         = "tts-1"

DEFAULT_PROVIDER     = "groq"
GROQ_BASE_URL        = "https://api.groq.com/openai/v1"
# Groq retired the free Llama 3.x models (moved to "Enterprise"); the current
# free chat models are the GPT-OSS family and Kimi K2. We keep an ordered
# fallback list and auto-advance on "model_not_found", so a Groq retirement can
# never brick the assistant again.
GROQ_CHAT_MODEL      = "openai/gpt-oss-120b"
GROQ_CHAT_FALLBACKS  = ["openai/gpt-oss-20b", "moonshotai/kimi-k2-instruct"]
GROQ_STT_MODEL       = "whisper-large-v3-turbo"
GROQ_STT_FALLBACKS   = ["whisper-large-v3"]
GROQ_TTS_MODEL       = "canopylabs/orpheus-v1-english"
GROQ_TTS_VOICE       = "troy"   # troy | autumn | hannah | austin | …
GROQ_VISION_MODEL    = "qwen/qwen3.6-27b"
GROQ_VISION_FALLBACK = "qwen/qwen3.8-27b"

_CONFIG_CACHE: dict = {"ts": 0.0, "cfg": {}}


def _cfg():
    try:
        return load_api_keys()
    except Exception:
        return {}


def get_api_key() -> str:
    """The active provider's key. Reads groq_api_key or openai_api_key
    (provider-aware), so switching providers never needs new plumbing."""
    data = _cfg()
    if provider() == "groq":
        key = data.get("groq_api_key") or data.get("openai_api_key")
    else:
        key = data.get("openai_api_key") or data.get("groq_api_key")
    return str(key or "").strip()


def model(name: str) -> str:
    return str(_cfg().get(name, "") or "").strip()


def provider() -> str:
    """Which backend is active: 'groq' (free default) or 'openai'."""
    data = _cfg()
    p = str(data.get("provider") or "").strip().lower()
    if p in {"groq", "openai"}:
        return p
    # Auto-detect: an OpenAI key (and no Groq key) → openai; otherwise groq.
    if data.get("openai_api_key") and not data.get("groq_api_key"):
        return "openai"
    return DEFAULT_PROVIDER


def chat_model() -> str:
    override = model("chat_model")
    if override:
        return override
    return GROQ_CHAT_MODEL if provider() == "groq" else DEFAULT_CHAT_MODEL


def tts_model() -> str:
    return model("tts_model") or DEFAULT_TTS_MODEL


def tts_voice() -> str:
    return model("tts_voice") or DEFAULT_TTS_VOICE


def stt_model() -> str:
    override = model("stt_model")
    if override:
        return override
    return GROQ_STT_MODEL if provider() == "groq" else DEFAULT_STT_MODEL


def image_model() -> str:
    return model("image_model") or DEFAULT_IMAGE_MODEL


def temperature() -> float:
    try:
        return float(_cfg().get("temperature", 0.7))
    except (TypeError, ValueError):
        return 0.7


def _model_unavailable(err: Exception) -> bool:
    """True if the provider rejected the model id (retired / no access)."""
    code = getattr(err, "status_code", None) or getattr(err, "code", None)
    text = str(err)
    return (
        code in (404, 402)
        or "model_not_found" in text
        or "does not exist" in text
        or "no longer" in text.lower()
        or ("not found" in text.lower() and "model" in text.lower())
    )


def _chat_models() -> list[str]:
    """Ordered chat-model candidates for the active provider (first valid wins)."""
    if provider() != "groq":
        return [chat_model()]
    out = [chat_model()]
    for m in GROQ_CHAT_FALLBACKS:
        if m not in out:
            out.append(m)
    return out


def _stt_models() -> list[str]:
    """Ordered STT-model candidates for the active provider."""
    if provider() != "groq":
        return [stt_model()]
    out = [stt_model()]
    for m in GROQ_STT_FALLBACKS:
        if m not in out:
            out.append(m)
    return out


def _client():
    from openai import OpenAI
    kwargs = {"api_key": get_api_key(), "max_retries": 2, "timeout": 60.0}
    if provider() == "groq":
        kwargs["base_url"] = GROQ_BASE_URL
    return OpenAI(**kwargs)


# ── chat ──────────────────────────────────────────────────────────────────────

def chat(messages: list[dict], tools: list[dict] | None = None,
         max_tokens: int | None = None, temp: float | None = None) -> dict:
    """Send messages and return {"text": str, "tool_calls": [...]}.

    messages: OpenAI chat format (role: system/user/assistant/tool).
    tools:    OpenAI tool format (type:"function" ...).
    """
    client = _client()
    last_err: Exception | None = None
    for model_id in _chat_models():
        kwargs: dict = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature() if temp is None else temp,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if _model_unavailable(e):
                print(f"[LLM] Model {model_id!r} unavailable — trying next…")
                continue
            raise

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
        return {"text": (msg.content or "").strip(), "tool_calls": tool_calls}

    raise (last_err or RuntimeError("no chat model available"))


def chat_with_image(prompt: str, image_bytes: bytes, mime: str = "image/png") -> str:
    """Ask a vision-capable model about an image. Returns its text answer."""
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

def transcribe_wav(wav_bytes: bytes) -> str:
    """Transcribe a WAV audio blob with Whisper. Returns text ('' on failure)."""
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
    if provider() == "groq":
        try:
            return _orpheus_tts(text)
        except Exception as e:  # noqa: BLE001
            print(f"[TTS] Orpheus failed ({e}); falling back to macOS 'say'.")
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
    """macOS built-in 'say' voice → WAV bytes (free, offline). Raises on failure."""
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


def _convert_schema(schema: dict) -> dict:
    out = {}
    t = schema.get("type")
    if t:
        mapped = _TYPE_MAP.get(str(t).upper(), str(t).lower())
        out["type"] = mapped
    desc = schema.get("description")
    if desc:
        out["description"] = str(desc)
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
                "description": decl.get("description", ""),
                "parameters": _convert_schema(params),
            },
        })
    return tools
