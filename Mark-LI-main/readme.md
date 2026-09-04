# ⚙️ ADHITHIYA

### A real-time, voice-first personal AI assistant for your Mac

ADHITHIYA is a JARVIS-style assistant that hears you, talks back, sees your
screen, and controls your computer — by voice. It runs on the **Gemini Live**
API for ultra-low-latency, two-way voice conversation.

> **Based on** [Mark-LI](https://github.com/FatihMakes/Mark-LI) by **FatihMakes**
> (Creative Commons BY-NC 4.0 — personal, non-commercial use). This repo is a
> rebranded, cleaned-up fork.

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

> Requirements: Python 3.11–3.13 (from python.org) · a microphone · a Gemini API key.

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

On first launch, enter your **Gemini API key** (free from
[aistudio.google.com](https://aistudio.google.com)). When macOS asks, allow
**microphone, camera, Accessibility and Screen Recording** in
*System Settings → Privacy & Security*.

> ### 🍎 On macOS 12 (Monterey)?
> Use **Python 3.11 or 3.12**. The launchers auto-detect macOS 12 and install
> `requirements-macos12.txt` — versions of PyQt6, opencv and numpy that still
> support Monterey (the newest releases require macOS 13+). This happens
> automatically; you don't need to do anything extra.

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
   `"study_audio_device"` in `config/api_keys.json` to your BlackHole device)

Notes are saved to `~/.adhithiya/notes/` as Markdown. Then ask:
*"summarize my notes"* · *"read my notes"* · *"export my notes"* · *"add a note:
<text>"* · *"open NotebookLM"*.

---

## ⚙️ Configuration

Everything lives in `config/api_keys.json` (created on first run, **never
committed**). Useful options:

```json
{
  "gemini_api_key": "AIza…",
  "assistant_name": "ADHITHIYA",
  "user_name": "",
  "fast_response": true,
  "morning_brief_enabled": true,
  "live_model": "models/gemini-2.5-flash-native-audio-preview-12-2025",
  "voice_name": "Charon",
  "audio_prebuffer_ms": 80,
  "audio_blocksize": 512,
  "ui_color": "#00d4ff"
}
```

| Key | What it does |
| --- | --- |
| `assistant_name` / `user_name` | Change what it calls itself / you |
| `fast_response` | `true` = fastest responses; `false` = enable emotional tone + background-chatter awareness |
| `live_model` | The Gemini Live model. **If Google retires a preview model, change it here** — no code edits needed |
| `voice_name` | Gemini voice (e.g. `Charon`, `Fenrir`, `Kore`, `Leda`, `Orus`, `Puck`, `Zephyr`) |
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
├── main.py                  # Core loop — Gemini Live session, audio I/O, tool dispatch
├── ui.py                    # PyQt6 HUD — orb/face, waveform, log, plugin manager, camera
├── core/                    # prompt, plugin loader, voice gate, agent, self-recovery
├── actions/                 # 20+ skills (search, files, vision, reminders, weather…)
├── plugins/                 # drop-in skills (calendar, notes, study mode, pomodoro…)
├── memory/                  # long-term memory + adaptive learning
├── dashboard/               # FastAPI phone-remote (QR pairing)
├── config/api_keys.json     # your API key + settings (gitignored)
└── face.png                 # HUD avatar (replace with your own if you like)
```

---

## 🧩 Writing your own plugin

Copy `plugins/_template.py`, fill in the `PLUGIN` dict and a `run()` function,
drop it in `plugins/`, restart. A broken plugin can never crash the app — it just
shows as *BROKEN* in the Plugin Manager.

---

## 📄 License

Personal and non-commercial use only.
Licensed under [Creative Commons BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
Original project: **Mark-LI** by **FatihMakes**.
