# ⚙️ ADHITHIYA

### A real-time, voice-first personal AI assistant for your Mac

ADHITHIYA is a cinematic, voice-first assistant that hears you, talks back, sees
your screen, and controls your computer — by voice. The AI brain runs on
**Groq by default — completely free, no credit card** — with OpenAI as an
optional paid upgrade, both behind one provider layer (`core/llm.py`), so
swapping is a one-line config change.

- **Free (default):** Groq — `openai/gpt-oss-120b` chat (auto-falls back to
  `gpt-oss-20b` / `kimi-k2`), `whisper-large-v3-turbo` speech-to-text, an
  **Orpheus** voice for speech (falls back to your Mac's `say`), and a **Qwen**
  vision model for "look at my screen" (preview — see the note below).

  > **One-time step:** the Orpheus voice needs you to accept its terms once at
  > [console.groq.com/playground?model=canopylabs%2Forpheus-v1-english](https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english)
  > — otherwise ADHITHIYA speaks with your Mac's voice (everything else works).
- **Fully local (free forever, private, offline):** Ollama chat on your own Mac
  (`qwen3:8b` by default — the best 8B-class tool-calling brain of 2026) + your
  Mac's built-in `say` voice. Hearing uses local whisper if installed, otherwise
  your free Groq key. Nothing breaks when a cloud provider changes its mind.
- **🧠 Built-in brain (NEW — $0 forever, no key, no Ollama):** a real neural
  net that lives on your Mac. One download (~1–2 GB, model size picked
  for your hardware) and ADHITHIYA thinks entirely
  offline — no account, no API key, no credit card, no internet needed. See the
  section below.
- **Paid (optional):** OpenAI — `gpt-4o-mini` chat, `whisper-1`, OpenAI TTS, and
  `gpt-image-1` image generation (creating images still needs OpenAI).

---

## 🧠 Run on the built-in brain (no key · no Ollama · no bill)

The assistant now ships with its **own brain**: a small open-weight model
(Qwen2.5-Instruct, Apache-2.0) run by llama.cpp's `llama-server` — both
downloaded **once** into `~/.adhithiya/brain/`, then running forever on your
machine. No account. No subscription. No internet. It cannot be switched off by
a provider, and it never sends your voice or screen anywhere.

1. Launch ADHITHIYA.
2. On the setup screen click **"INSTALL BUILT-IN BRAIN — free, offline, no key"**.
3. **That's it.** The app does everything from here and reports each step in
   the log: installs `cmake` if missing, opens Apple's Xcode installer if
   needed (click **Install** once), compiles the engine (macOS 12, one-time),
   downloads the model (auto-sized, resumable), starts the brain and warms
   it. Offline hearing (`faster-whisper`) is also installed automatically
   when Python 3.12 is present. When the log says the brain is online, talk
   to it.

Power users can run the same full setup from the terminal in one command
(also writes `"provider": "builtin"` into the config):

```
python3 -m core.builtin_brain bootstrap
python3 -m core.builtin_brain status           # what's installed
python3 -m core.builtin_brain start / stop / restart
```

**Model profiles** — your machine's power dial (set `"builtin_profile"` in
`config/api_keys.json`):

| Profile | Model | Size | What you get |
|---|---|---|---|
| `tiny` | Qwen2.5 0.5B Q4 | ≈ 0.5 GB | instant replies, basic chat |
| `fast` | Qwen2.5 1.5B Q4 | ≈ 1 GB | quick answers, decent smarts |
| `balanced` | Qwen2.5 3B Q4 | ≈ 2 GB | **recommended default** — strong reasoning + tools, still conversational speed |
| `strong` | Qwen2.5 7B Q4 | ≈ 4.7 GB | **max power** — biggest model your Mac can hold; replies take patience |

**How powerful is it really?** On a 2015 dual-core i5 like the Early-2015
MacBook Pro: `balanced` answers in a few seconds per sentence and is the
sweet spot; `strong` thinks much harder but each answer can take many seconds
to minutes. If no profile is configured, ADHITHIYA picks `balanced` for
16 GB machines (even modest CPUs), `fast` only for ≤ 2-core/8 GB combos, and
`tiny` under 8 GB RAM. On Apple Silicon, `balanced` is near-instant.

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

On Apple Silicon replies flow at reading speed; on Intel Macs expect a bit of
thinking time (the `tiny`/`fast` profiles stay snappy). Any other GGUF can be
used via `"builtin_model_url": "https://…/model.gguf"`.

**Which engine your macOS gets** (picked automatically; verified against the
official llama.cpp binaries):

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

Hearing & voice are the same as Ollama local mode: ADHITHIYA speaks with your
Mac's `say` voice for free. For hearing, the app auto-installs offline
`faster-whisper` when running on Python 3.12 (the launcher prefers it on
macOS 12); otherwise it will happily use a free Groq key **if you add one**
(the brain itself never needs it). Vision and image generation still need a
cloud provider — the built-in brain is a text brain.

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
- 📱 **Remote dashboard** — control it from your phone via QR code pairing. Fully two-way: speak or type from the phone, and ADHITHIYA's **voice answers play on the phone too** (🔊 toggle), so the assistant "lives" across both devices — the Mac and your phone stay in sync
- 📚 **Study buddy** — say *"take notes for my class"* and it records the lecture audio, transcribes it live, and writes running notes. Then *"summarize my notes"* turns them into a study guide, *"read my notes"* reads them back, and *"export my notes"* saves them to your Desktop. Works with the existing NotebookLM + flashcards (drop notes into your signed-in NotebookLM browser session)
- 🎨 **Customization** — change the assistant name, your name, and the whole UI colour
- ⚡ **Auto-start at login**, desktop shortcut, system tray, hotkeys (F4 mute · F11 fullscreen · Esc interrupt)

---

## 🚀 Quick start (macOS)

### Option A — double-click to run (quickest)

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

On first launch, enter your **Groq API key** — free from
[console.groq.com](https://console.groq.com), no card needed. (To use the paid
OpenAI brain instead, set `"provider": "openai"` in the config and enter an
OpenAI key.) When macOS asks, allow **microphone, camera, Accessibility and
Screen Recording** in *System Settings → Privacy & Security*.

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

| Key | What it does |
| --- | --- |
| `provider` | Which brain to use: `groq` (free, default), `builtin` (offline brain built into the app), `local` (Ollama) or `openai` (paid) |
| `groq_api_key` / `openai_api_key` | API key for the active provider (`builtin`/`local` need none) |
| `builtin_profile` | Built-in brain size: `tiny`/`fast`/`balanced` (auto default) /`strong` |
| `builtin_max_tokens` | Longest single reply in tokens (default `1024`; raise for essays) |
| `builtin_hybrid` | Auto-power routing (`false` = strictly local · `true` = cloud-first · unset = auto). Needs a saved `groq_api_key` |
| `builtin_model_url` | Optional custom GGUF URL — replaces the profile download |
| `builtin_engine_version` | llama.cpp engine build pin (default `b10839`) |
| `builtin_port` | Localhost port for the built-in brain service (default `18771`) |
| `builtin_ctx_size` | Context window in tokens (default `8192`) |
| `builtin_gpu_layers` | GPU offload layers (Apple Silicon: try `99`; default `0` = CPU) |
| `assistant_name` / `user_name` | Change what it calls itself / you |
| `chat_model` | Chat model (Groq default `openai/gpt-oss-120b`; OpenAI default `gpt-4o-mini`) |
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
