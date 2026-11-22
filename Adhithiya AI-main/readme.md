# ⚙️ ADHITHIYA

### A real-time, voice-first personal AI assistant for Windows (also supports macOS/Linux)

ADHITHIYA is a voice-first assistant that hears you, talks back, sees your
screen, and controls your computer. It selects the cloud provider from the
configured API key when `provider` is omitted; there is **no implicit cloud
provider**. Groq is a free option, with OpenAI and OpenAI-compatible gateways
also supported through one provider layer (`core/llm.py`).

- **Free option:** Groq — `openai/gpt-oss-120b` chat (auto-falls back to
  `gpt-oss-20b` / `kimi-k2`), `whisper-large-v3-turbo` speech-to-text, and an
  **Orpheus** voice (falls back to Windows' built-in speech on Windows, or
  `say` on macOS). A **Qwen** vision model handles "look at my screen" requests.

  > **One-time step:** the Orpheus voice needs you to accept its terms once at
  > [console.groq.com/playground?model=canopylabs%2Forpheus-v1-english](https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english)
  > — otherwise ADHITHIYA uses your computer's built-in speech voice.
- **Fully local (free forever, private, offline):** Ollama chat on your
  computer (`qwen3:8b` by default) plus the operating system's built-in speech
  voice. Hearing uses local Whisper if installed, otherwise your free Groq key.
- **🧠 Built-in brain (NEW — $0 forever, no key, no Ollama):** a real neural
  net that lives on your computer. One download (model size selected for your
  hardware) and ADHITHIYA thinks offline — no account, API key, or subscription.
  See the section below.
- **Paid (optional):** OpenAI — `gpt-4o-mini` chat, `whisper-1`, OpenAI TTS, and
  `gpt-image-1` image generation (creating images still needs OpenAI).
- **Gateway (optional):** route chat through any OpenAI-compatible gateway.
  Choose **OPENAI-COMPATIBLE GATEWAY** on setup and enter its base URL and API
  key. The default endpoint/model target OpenRouter; the model ID is optional.
  Tool calling depends on the model. Speech-to-text and speech output require a
  gateway that also proxies OpenAI audio APIs (OpenRouter chat alone does not).

---

## 🧠 Run on the built-in brain (no key · no Ollama · no bill)

The assistant now ships with its **own brain**: a small open-weight model
(Qwen2.5-Instruct, Apache-2.0) run by llama.cpp's `llama-server` — both
downloaded **once** into `~/.adhithiya/brain/`, then running forever on your
machine. No account. No subscription. No internet. It cannot be switched off by
a provider, and it never sends your voice or screen anywhere.

1. Launch ADHITHIYA.
2. On the setup screen click **"INSTALL BUILT-IN BRAIN — free, offline, no key"**.
3. **That's it.** The app reports each step in the log: it downloads the
   platform-specific llama.cpp engine and a model (auto-sized and resumable),
   starts the local brain, then warms it. Older macOS versions may need a
   one-time engine compile with Apple's Xcode tools. Source installs can
   install `faster-whisper` for offline hearing; the Windows `.exe` build
   includes its code and downloads the speech model when first used. When the
   log says the brain is online, talk to it.

Power users can run the same full setup from a terminal (also writes
`"provider": "builtin"` into the config):

```powershell
# Windows PowerShell, from the project folder
py -3.12 -m core.builtin_brain bootstrap
py -3.12 -m core.builtin_brain status
py -3.12 -m core.builtin_brain start
```

On macOS/Linux, use `python3 -m core.builtin_brain bootstrap` and the same
`status`, `start`, `stop`, or `restart` actions.

**Model profiles** — your machine's power dial (set `"builtin_profile"` in
`config/api_keys.json`):

| Profile | Model | Size | What you get |
|---|---|---|---|
| `tiny` | Qwen2.5 0.5B Q4 | ≈ 0.5 GB | instant replies, basic chat |
| `fast` | Qwen2.5 1.5B Q4 | ≈ 1 GB | quick answers, decent smarts |
| `balanced` | Qwen2.5 3B Q4 | ≈ 2 GB | **recommended default** — strong reasoning + tools, still conversational speed |
| `strong` | Qwen2.5 7B Q4 | ≈ 4.7 GB | **max power** — largest profile; replies take patience and need sufficient free RAM |

**How powerful is it really?** Performance depends on your CPU and available
memory. `balanced` is a practical default; `strong` reasons more deeply but
can take much longer on a CPU-only computer. If no profile is configured,
ADHITHIYA picks `balanced` for 16 GB machines, `fast` for lower-memory / low-core
systems, and `tiny` under 8 GB RAM. Apple Silicon and modern GPUs can make local
responses much faster.

> Tip: for essay-length answers raise the reply cap with
> `"builtin_max_tokens": 4096` in config (default 1024; tool loops always
> continue past it).

**Auto-power hybrid (best of both worlds, still $0):** save a free Groq key
in config and the built-in brain automatically routes **heavy requests**
(long prompts, "summarize/explain/compare/write…") to Groq's free
`gpt-oss-120b`-class cloud brain while everyday chat stays on the fast local
brain — and if the internet is down, the local brain answers everything.
Control it with `"builtin_hybrid"` in config: `false` = strictly local &
private, `true` = always cloud-first, unset = auto. (This is exactly the
"powerful when it matters, private when it counts" mode.)

Max-power all the time: set `"provider": "groq"` — every turn uses the
~120B-class free brain (needs internet + free key; no card).

On supported Windows x64 computers, ADHITHIYA downloads the matching official
llama.cpp engine automatically; macOS uses the release appropriate for its
version. Any compatible GGUF can be used via `"builtin_model_url":
"https://…/model.gguf"`.

**macOS engine compatibility** (picked automatically):

| macOS | Engine |
|---|---|
| 15.5+ | newest build (b10839) — full features |
| 14.2 – 15.4 | b6500 — still has tool calling |
| 12.x – 14.1 | no official prebuilt can call tools → **compile once** (below) |

**Built-in brain on macOS 12/13 (e.g. Monterey on older Macs):** official
llama.cpp binaries with tool calling only exist for macOS 14.2+, so the app
**compiles the engine on your Mac instead** — fully automatic too. When you
click the setup button it opens Apple's "Xcode Command Line Tools" installer
once (click **Install**, ~10 min), installs `cmake` itself, then compiles
(~15–25 min, one time). Every step is in the log. If you prefer the terminal:

```
python3 -m core.builtin_brain bootstrap   # = everything (see above)
```

Everything after that is identical: model download is resumable, the brain
runs offline, and the app starts/warms it automatically at launch.

Hearing and speech use your operating system's voice stack. Windows uses its
built-in SAPI voice; macOS uses `say`. Source installs can automatically add
`faster-whisper` for offline hearing, and the Windows `.exe` includes the
runtime code (the Whisper model is downloaded on first use). If you don't have
offline Whisper available, add a free Groq key for speech-to-text — the brain
itself never needs one. Vision and image generation still need a cloud
provider; the built-in brain is text-only.

> **Licence note:** Qwen2.5 is Apache-2.0 (free for any use, including
> commercial). Engine builds come from [llama.cpp](https://github.com/ggml-org/llama.cpp)
> (MIT), pinned to a known-good release and fetched from the official GitHub
> releases at first launch.

---

1. Install **Ollama** from [ollama.com](https://ollama.com) and start it once.
2. In Terminal, pull a model (one-time, ~5 GB):
   ```
   ollama pull qwen3:8b
   ```
   *Need it snappier?* `ollama pull qwen3:4b` (then set `"local_model": "qwen3:4b"`).
   *Want maximum quality and don't mind waiting?* `ollama pull qwen3:14b` (16 GB RAM only).

   > Interrupted a pull? Just re-run the command — Ollama keeps the partial
   > download and resumes where it left off. ADHITHIYA also auto-detects
   > **whatever model you've pulled**, so you don't have to edit any config.

3. Launch ADHITHIYA and click **"RUN FULLY LOCAL — no key needed"** on the setup
   screen — or set `"provider": "local"` in `~/.adhithiya/config/api_keys.json`.

Hearing: ADHITHIYA uses your free Groq key for speech-to-text if one is already
saved (the brain itself never needs it). Fully offline hearing needs
`faster-whisper`, but note: on macOS 12 that requires **Python 3.12** — its
onnxruntime dependency has no Python 3.13 build for macOS older than 13.

---

## ✨ What it can do

- 🎙️ **Real-time voice** — talk naturally in any language; it replies in the same language
- 🖥️ **Computer control** — open apps, volume/brightness, windows, keyboard, mouse, restart/shutdown (with confirmation)
- 👁️ **Vision** — capture your screen or webcam and answer questions about what it sees
- 🌐 **Web** — search (news / research / price / compare), browser control, YouTube, flights, weather
- 📂 **Files** — drop any file in and ask: summarize a PDF, explain code, analyze a CSV, resize an image, transcribe audio…
- 🧠 **Memory** — remembers your name, preferences, projects and language across sessions
- 👤 **Knows it's you** — it recognises you as its owner: greets you by name, learns who you are over time, and (if you enrol your voice once) confirms *"it's you"* when it hears you speak
- 🎓 **Self-learning** — when a command fails, it searches the web itself, works out the correct way, remembers the fix, and uses it next time (stored in `memory/learned_procedures.json`)
- 🌅 **Morning briefing** — greets you, tells the time, recaps yesterday and reads today's news
- 🧩 **Plugin system** — drop a `.py` file into `plugins/` to teach it a new skill (no code changes needed)
- 🛠️ **Builds its own abilities** — ask for something it can't do yet and it writes a brand-new plugin itself, safety-checks it, shows you a preview, and (once you confirm) installs it live — saved to `~/.adhithiya/plugins/` so it's remembered forever
- 🤖 **Autonomous agent (`run_task`)** — give it one goal and it plans and executes a whole multi-step job by itself: search the web, read pages, work with files, run safe dev commands, set reminders, check calendar/notes, even generate images — then reports back. (Can't delete/send/restart — those still ask you.)
- 🖼️ **Image generation** — "draw me a wallpaper of…" and it creates an image saved to your Pictures folder
- 📄 **Deep web reading (`web_fetch`)** — reads the actual page behind any link and summarises it
- 📱 **Remote dashboard** — control it from your phone via QR code pairing. Fully two-way: speak or type from the phone, and ADHITHIYA's **voice answers play on the phone too** (🔊 toggle), so the assistant "lives" across both devices — your computer and phone stay in sync
- 📚 **Study buddy** — say *"take notes for my class"* and it records the lecture audio, transcribes it live, and writes running notes. Then *"summarize my notes"* turns them into a study guide, *"read my notes"* reads them back, and *"export my notes"* saves them to your Desktop. Works with the existing NotebookLM + flashcards (drop notes into your signed-in NotebookLM browser session)
- 🎨 **Customization** — change the assistant name, your name, and the whole UI colour
- ⚡ **Auto-start at login**, desktop shortcut, system tray, hotkeys (F4 mute · F11 fullscreen · Esc interrupt)

---

## 🚀 Quick start

### Windows 10/11 — run from source

1. Install **64-bit Python 3.11, 3.12, or 3.13** from
   [python.org](https://www.python.org/downloads/windows/). The Python Launcher
   (`py`) is recommended.
2. Extract the project folder and double-click **`run_adhithiya.bat`**. On its
   first run it creates a virtual environment and installs the app's packages;
   then it starts ADHITHIYA. Keep the project folder in place so the launcher
   and environment remain available.
3. On the setup screen enter a free **Groq API key** from
   [console.groq.com](https://console.groq.com), or select a no-key local brain.
   Allow microphone/camera access in **Windows Settings → Privacy & security**
   if Windows asks.

### Build a standalone Windows `.exe`

On Windows, double-click **`build_windows.bat`**. It creates a single
**`dist/ADHITHIYA.exe`** with the app dependencies and offline Whisper runtime
included; Python is not needed on the computer where the `.exe` runs. The
built-in brain and its model download into `%USERPROFILE%\.adhithiya`; Whisper
model weights use the Hugging Face cache under your user profile. Diagnostic
output is written to `%USERPROFILE%\.adhithiya\app.log`. The build must run
on Windows (PyInstaller cannot cross-build a Windows executable from macOS/Linux).
A matching GitHub Actions job also builds it on pull requests or when manually
run, and uploads an `ADHITHIYA-Windows` artifact. This unsigned self-build may
trigger a Windows SmartScreen warning.

### macOS — double-click to run (quickest)

Just double-click **`run_adhithiya.command`** in Finder. It sets up Python
dependencies automatically on first run (one-time ~1–2 GB download), then
launches ADHITHIYA. If macOS blocks it, right-click → **Open**.

> Requirements: Python 3.11–3.13 (from python.org) · a microphone · a free Groq API key.

### Option B — build a real standalone `.app`

Double-click **`build_app.command`**. It builds `dist/ADHITHIYA.app` — a
self-contained app you can drag into `/Applications` and launch like any Mac app
(no Terminal, no Python needed).

- First launch: **right-click → Open** to allow the unsigned app (Gatekeeper).
- Your API key, memory and settings are stored in `~/.adhithiya/` (never inside
  the app bundle), so updating the app won't wipe them.

### Option C — run from source (developers)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

On first launch, choose **AUTO — detect from API key** and enter one key
(known Groq, OpenAI, and OpenRouter key formats are detected), or select its
provider explicitly. For a custom OpenAI-compatible gateway, choose
**OPENAI-COMPATIBLE GATEWAY** and enter its URL and key; the model ID is
optional and uses `openrouter/auto` unless overridden. A single saved key is
enough; no `provider` or `chat_model` entry is required. Settings are saved
locally in
`~/.adhithiya/config/api_keys.json`. On macOS, allow **microphone, camera,
Accessibility and Screen Recording** in *System Settings → Privacy & Security*
when prompted.

> ### 🍎 On macOS 12 (Monterey)?
> Use **Python 3.11–3.13**. The launchers auto-detect macOS 12 and install
> `requirements-macos12.txt` — versions of PyQt6, opencv and numpy that still
> ship macOS 12-compatible wheels (the newest releases require macOS 13+).
> This happens automatically; you don't need to do anything extra. The
> launcher also picks the best installed Python and rebuilds a stale virtual
> environment if its Python was removed.

### 📚 Study buddy — taking notes during a class

Say *"take notes for my biology class"* and ADHITHIYA records + transcribes the
lecture in the background, then *"stop notes"* when it ends. By default it
records from the **microphone** (picks up your speakers). To capture the
**computer's audio directly** (cleaner, no room noise):

1. Install the free [BlackHole](https://existential.audio/blackhole/) virtual
   audio driver
2. In **Audio MIDI Setup**, create a *Multi-Output Device* containing your
   speakers **and** BlackHole, and set it as the Mac's output — so you still
   hear the class while ADHITHIYA records it
3. In ADHITHIYA say: *"take notes for my class using system audio"* (or set
   `"study_audio_device"` in `~/.adhithiya/config/api_keys.json` to your BlackHole device)

Notes are saved to `~/.adhithiya/notes/` as Markdown. Then ask:
*"summarize my notes"* · *"read my notes"* · *"export my notes"* · *"add a note:
<text>"* · *"open NotebookLM"*.

---

## ⚙️ Configuration

Everything lives in `~/.adhithiya/config/api_keys.json` (created on first run, **never
committed**). Useful options:

```json
{
  "provider": "groq",
  "groq_api_key": "gsk-…",
  "assistant_name": "ADHITHIYA",
  "user_name": "",
  "chat_model": "openai/gpt-oss-120b",
  "stt_model": "whisper-large-v3-turbo",
  "say_voice": "",
  "morning_brief_enabled": true,
  "audio_prebuffer_ms": 80,
  "audio_blocksize": 512,
  "ui_color": "#00d4ff"
}
```

For a gateway, choose it in the setup screen or use a configuration like this
(replace the placeholder locally; the model line is optional and defaults to
`openrouter/auto`; do not commit your key):

```json
{
  "provider": "gateway",
  "gateway_api_key": "YOUR_GATEWAY_API_KEY",
  "gateway_base_url": "https://openrouter.ai/api/v1"
}
```

| Key | What it does |
| --- | --- |
| `provider` | Optional explicit brain selection: `groq`, `openai`, `gateway`, `builtin` or `local`. If omitted, one saved cloud key selects its provider; multiple keys require an explicit choice |
| `groq_api_key` / `openai_api_key` / `gateway_api_key` | Provider-specific API key; a single key is enough for automatic provider selection |
| `api_key` | Optional generic key; common `gsk_`, `sk-or-`, and `sk-` prefixes are detected (otherwise choose the provider explicitly) |
| `gateway_base_url` | OpenAI-compatible gateway base URL; default `https://openrouter.ai/api/v1`. `gateway_url` is accepted as an alias |
| `gateway_model` | Optional gateway chat model ID (default `openrouter/auto`; set this if your endpoint does not support auto-routing) |
| `gateway_chat_fallbacks` | Optional comma-separated model IDs to try if the gateway rejects the primary model |
| `builtin_profile` | Built-in brain size: `tiny`/`fast`/`balanced` (auto default) /`strong` |
| `builtin_max_tokens` | Longest single reply in tokens (default `1024`; raise for essays) |
| `builtin_hybrid` | Auto-power routing (`false` = strictly local · `true` = cloud-first · unset = auto). Needs a saved `groq_api_key` |
| `builtin_model_url` | Optional custom GGUF URL — replaces the profile download |
| `builtin_engine_version` | llama.cpp engine build pin (default `b10839`) |
| `builtin_port` | Localhost port for the built-in brain service (default `18771`) |
| `builtin_ctx_size` | Context window in tokens (default `8192`) |
| `builtin_gpu_layers` | GPU offload layers (Apple Silicon: try `99`; default `0` = CPU) |
| `assistant_name` / `user_name` | Change what it calls itself / you |
| `chat_model` | Optional general chat-model override (Groq default `openai/gpt-oss-120b`; OpenAI default `gpt-4o-mini`). The gateway uses `gateway_model` |
| `stt_model` | Speech-to-text model (Groq default `whisper-large-v3-turbo`; OpenAI default `whisper-1`) |
| `say_voice` | macOS voice used as the Groq speech **fallback** (e.g. `Samantha`); leave empty for the system voice |
| `groq_tts_voice` | Groq Orpheus voice — `troy`, `autumn`, `hannah`, `austin` (default `troy`) |
| `tts_voice` | OpenAI speaking voice — `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`, `coral`, `sage`, `ash`, `ballad` (OpenAI provider only) |
| `image_model` | OpenAI image model (default `gpt-image-1`) — *creating* images needs the `openai` provider; screen-vision on Groq uses Qwen |
| `audio_prebuffer_ms` | Jitter cushion before playback starts each turn (`0`–`1000`, default `80`). Higher = smoother but slightly slower first syllable; lower = snappier but more sensitive to network jitter |
| `audio_blocksize` | Output buffer size in frames (`0` = let the OS choose, default `512`). Smaller = lower latency |
| `ui_color` | UI accent colour (also changeable from the ⚙ menu) |

## 🛡️ Safety

ADHITHIYA has **one nature — no modes to switch**. It handles routine tasks
decisively (open apps, search, control the computer, manage files, set
reminders) and asks for **confirmation only** before irreversible or external
actions: sending messages, deleting files, cleaning the desktop, restarting or
shutting down.

- **Project work** — it can plan, edit files, and run tests for you. It never
  uses an unrestricted shell: a small allowlist of commands (python, pytest,
  git, …) is parsed without a shell, paths stay inside the workspace, and
  destructive, network, or out-of-workspace actions pause for your
  APPROVE/REJECT in the ⚙ menu. Just say e.g. *"add a new plugin"* or type
  `/agent plan <goal>`.
- **Self-built abilities** — when ADHITHIYA writes a new plugin for you, the
  code is restricted to a small safe import list (no shell, no network, no
  secrets), and it is never installed or run until you confirm.

---

## 🗂️ Project structure

```
├── main.py                  # Core loop — voice pipeline (STT → chat/tools → TTS), audio I/O, tool dispatch
├── ui.py                    # PyQt6 HUD — orb/face, waveform, log, plugin manager, camera
├── core/                    # prompt, plugin loader, voice gate, agent, self-recovery
│   └── builtin_brain.py     # 🧠 the built-in offline brain — engine+model installer, llama-server lifecycle
├── actions/                 # 20+ skills (search, files, vision, reminders, weather…)
├── plugins/                 # drop-in skills (calendar, notes, study mode, pomodoro…)
├── memory/                  # long-term memory + adaptive learning
├── dashboard/               # FastAPI phone-remote (QR pairing)
└── ~/.adhithiya/config/api_keys.json  # your API key + settings (persists across updates)
└── ~/.adhithiya/brain/      # the built-in brain: llama.cpp engine + GGUF model (downloaded once)
└── face.png                 # HUD avatar (replace with your own if you like)
```

---

## 🛠️ For developers

- **Architecture:** read [ARCHITECTURE.md](ARCHITECTURE.md) — provider layer,
  threading model, extension points and known debt.
- **Tests:** `python -m pytest tests/` (offline-safe, no API keys needed).
  CI runs syntax checks on every `.py` plus the full suite on Python
  3.11–3.13 for every push (`.github/workflows/ci.yml`).

## 🧩 Writing your own plugin

Copy `plugins/_template.py`, fill in the `PLUGIN` dict and a `run()` function,
drop it in `plugins/`, restart. A broken plugin can never crash the app — it just
shows as *BROKEN* in the Plugin Manager.

---

## 📄 License

Personal and non-commercial use only.
Licensed under [Creative Commons BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
