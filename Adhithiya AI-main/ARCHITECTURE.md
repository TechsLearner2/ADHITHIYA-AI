# ADHITHIYA — Architecture

A voice-first personal AI assistant for Windows (also runs on macOS/Linux,
with a few operating-system-specific skills). Voice in → AI brain with tools →
voice/UI out. Windows source launch uses `run_adhithiya.bat`; the single-file
Windows build is created on Windows with `build_windows.bat`.

```
        ┌────────────────────────────────────────────────────────────┐
        │                     main.py (AdhithiyaAssistant)           │
        │   mic → STT (core.llm.transcribe_wav) → transcript queue   │
        │        → _chat_turn (LLM + tool loop, ≤8 rounds)           │
        │        → speak queue → TTS (core.llm.tts_wav) → speakers   │
        │        └─ every hop is a thread; UI updates via Qt signals │
        └───────────────┬────────────────────────────────────────────┘
                        │ chat(messages, tools)   [one door]
        ┌───────────────▼────────────────────────────────────────────┐
        │              core/llm.py  — the provider layer             │
        │   provider(): groq | openai | gateway | local | builtin  │
        │   gateway → configured OpenAI-compatible URL/key/model     │
        │   builtin → llama-server on 127.0.0.1:18771 (auto-managed) │
        │   builtin hybrid → heavy turns to Groq cloud (auto-power)  │
        └───────┬───────────────┬───────────────┬────────────────────┘
      tools     │               │ memory        │ plugins
        ┌───────▼──────┐  ┌─────▼──────────┐ ┌──▼───────────────────┐
        │ actions/ (24)│  │ memory/        │ │ core/plugin_loader   │
        │ open_app,    │  │ long-term mem, │ │ plugins/ (21 drop-in │
        │ web_search,  │  │ adaptive learn,│ │ skills; plugin_builder│
        │ screen, …    │  │ self-learning  │ │ writes new ones)     │
        └───────┬──────┘  └─────┬──────────┘ └──────────────────────┘
                │               │ learned fixes (web-derived) are
                │               │ sanitised against prompt injection
        ┌───────▼────────────────▼───────────────────────────────────┐
        │  ui.py (PyQt6) — orb/face HUD, waveform, log, overlays,   │
        │  dashboard/server.py — FastAPI phone remote (QR pairing)  │
        └────────────────────────────────────────────────────────────┘
```

## The one door: `core/llm.py`

Every AI call goes through this module; swapping brains is a config change,
never a code change. Each provider implements the same surface:

| | chat | speech-to-text | speech-out | vision | image gen |
|---|---|---|---|---|---|
| `groq` (free option) | gpt-oss-120b + fallbacks | whisper-large-v3 | Orpheus → OS voice | Qwen | — |
| `openai` (paid) | gpt-4o-mini | whisper-1 | OpenAI TTS | yes | yes |
| `gateway` | configured `gateway_model` (OpenRouter `openrouter/auto` by default) | gateway-dependent | gateway-dependent | gateway-dependent | gateway-dependent |
| `local` (Ollama) | qwen3:8b + auto-detect | faster-whisper → Groq | OS voice | — | — |
| `builtin` (offline) | Qwen2.5 GGUF via llama.cpp | faster-whisper → Groq | OS voice | — | — |

If `provider` is omitted, one saved cloud key identifies its provider; there is
no implicit cloud default. Multiple provider keys require an explicit choice.
Chat-model selection follows the detected provider, so `chat_model` is optional.

Key properties: ordered model fallbacks (never bricked by a retired model),
retry-without-tools when a model can't function-call, `<think>` stripping,
busy counters (`local_busy()`) so the system monitor stands down while the
brain pins the CPU, and human-readable errors at every failure stage.

## The built-in brain: `core/builtin_brain.py` (stdlib only)

Installer + supervisor for llama.cpp's `llama-server`, stored in
`~/.adhithiya/brain/` (engine exe, GGUF model, `registry.json`, `server.log`).

- **bootstrap()** — the "just works" chain: download the platform-specific
  engine (Windows/Linux and newer macOS) or compile it on older macOS → model
  (profile auto-sized from CPU/RAM) → start → warm. Idempotent.
- Downloads are resumable, archives are extracted with symlink support and
  path-traversal guards; the server binds 127.0.0.1 only and exits with the
  app (`atexit`).
- `core/llm.py` imports **constants** only from it (no cycle); `ensure_server`
  is called lazily on the first chat.

## Threading model (why it doesn't deadlock)

- One event loop (`asyncio`) drives the assistant; blocking calls run via
  `asyncio.to_thread`.
- PyQt is GUI-thread only — `ui.write_log` emits a signal, never touches
  widgets off-thread.
- The `openai` package is imported exactly once on the main thread (a prior
  bug: submodule import locks deadlocked when first import happened from
  mic/dashboard threads).
- One config source of truth (`~/.adhithiya/config/api_keys.json`, atomic
  writes, 0600 perms) re-read per call — switching providers takes effect
  immediately, and per-call monkeypatching in tests stays trivial.

## Data & privacy boundaries

- `~/.adhithiya/` — config, memory, learned procedures, brain, notes, voice
  profile. Survives app updates; never committed.
- Keys never stored in the repo; learned web guidance is redacted, length
  capped, and filtered for prompt-injection wording; remote-content guidance
  is injected into prompts explicitly labelled *untrusted data*.
- Destructive/network/device-wide tool calls require explicit `confirmed`
  from the user (encoded in `core/prompt.txt` and enforced by actions).

## Extension points

- **New skill without code**: drop a `.py` into `plugins/` (see
  `plugins/_template.py`).
- **Brand-new ability**: ask ADHITHIYA — `plugin_builder` writes, tests, and
  (after your confirmation) installs a plugin.
- **New cloud/local brain**: implement the provider surface in `core/llm.py`
  and register the id in `provider()`/UI setup; everything downstream just
  works.

## Roadmap / known debt

- `ui.py` (~4,100 lines) and `main.py` (~2,200) are the maintainability
  hotspots; split into modules as features change.
- GitHub Actions CI runs syntax + tests on every push (`.github/workflows/ci.yml`).
- The Windows `.exe` is built on Windows with PyInstaller and bundles its
  Python runtime. The built-in brain stays in the user's data directory;
  faster-whisper keeps its model in the Hugging Face cache. On macOS 12, offline
  hearing requires Python 3.12, which the launcher auto-prefers.
