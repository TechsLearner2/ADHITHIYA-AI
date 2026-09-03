# ⚙️ MARK LI (51)
### The Ultimate Cross-Platform Personal AI Assistant — By FatihMakes

> 📺 **[Watch the full setup video on YouTube](https://www.youtube.com/@FatihMakes)**

A real-time voice AI that can hear, see, understand, and control your computer — on any OS. Supports Windows, macOS, and Linux. Built on the Gemini Live API for native audio streaming, delivering zero subscriptions and total digital autonomy.

---

## ✨ Overview

MARK LI is the final form of the core: an assistant you extend without ever touching its engine. Drop a single plugin file into the `plugins/` folder and JARVIS learns a new skill on the next launch — no code changes, no configuration, no risk. On top of that, the voice itself got smarter: JARVIS now hears the emotion in your voice, knows when you're talking to someone else in the room and stays silent, and can hold one conversation for hours without losing the thread.

It's not just an assistant — it's an extension of your digital life.

---

## 🚀 Capabilities

### Core Features
| Feature | Description |
|---|---|
| 🧩 Plugin System | Drop a single `.py` file into `plugins/` — JARVIS learns a new skill on next launch |
| 🎙️ Real-time Voice | Ultra-low latency conversation in any language via Gemini Live API |
| 💓 Affective Dialog | Hears the emotion in your voice and adapts its tone in response |
| 🤫 Proactive Audio | Knows when you're not talking to it — background chatter never triggers a reply |
| ♾️ Unlimited Sessions | Sliding-window context compression — one conversation can last for hours |
| 🖥️ System Control | Launch apps, adjust volume/brightness, WiFi, shortcuts, power — all by voice |
| 🧩 Autonomous Tasks | Opt-in, project-scoped planning, editing, and testing via Agent Mode |
| 👁️ Visual Awareness | Real-time screen capture and webcam vision piped into your main Gemini session |
| 🧠 Persistent Memory | Deeply remembers projects, preferences, and personal context across sessions |
| ⌨️ Hybrid Input | Seamlessly switch between keyboard typing and voice commands |
| 🌅 Morning Briefing | On first boot: greets you, reads the time, recaps yesterday, and fetches live news |
| 🔔 Proactive 2.0 | Time-aware, context-aware check-ins — knows the time of day, your projects, and what you've been discussing |
| 🗓️ Session Memory | Summarises each conversation and mentions it naturally next morning — consumed after use, never repeats |
| 👁️‍🗨️ Background Monitoring | User-configured topic watching — checks for new headlines once a day and alerts naturally |
| 📊 Hardware Monitoring | Continuous CPU, RAM, GPU and temperature telemetry with localized voice alerts |
| 🌤️ Weather Report | Live weather data for your city, personalized from memory |
| 🗺️ Dynamic Content Panel | Scrollable display layer beneath the HUD that renders web results, news, and search data |
| 🔍 Multi-Mode Web Search | `news` / `research` / `price` / `compare` / `search` — Gemini Grounded first, DDG fallback |
| ⏰ Smart Reminders | OS-native scheduled notifications (Windows Task Scheduler / macOS LaunchAgent / Linux systemd) |
| ✈️ Flight Finder | Live flight price and availability lookup |
| 🎮 Game Updater | Checks and triggers game updates on Steam and Epic Games on demand |
| 📂 File Processor | Read, summarize, and answer questions about local files |
| 💻 Code Helper | Inline code review, debugging, and generation |
| 🌐 Browser Control | Open URLs, navigate tabs, and interact with the browser by voice |
| 📨 Send Message | Compose and send messages through WhatsApp, Telegram, and more |
| 🎬 YouTube Control | Search, play, and control YouTube playback by voice |
| 🖱️ Desktop Control | Taskbar, window management, and desktop-level operations |
| 🧑‍💻 Silent Language Memory | Detects spoken language on first use — all future sessions adapt automatically |
| 📱 Remote Dashboard | Control the assistant from your phone via QR code pairing |
| ⚡ Auto-Start on Boot | Registers with the OS startup system (registry / LaunchAgent / .desktop) |
| 📋 Clipboard Intelligence | Copy any text → floating panel with Translate / Summarise / Explain / Fix |
| 🎨 Assistant Customization | Change the assistant name and your name from the UI — takes effect immediately |

---

### Included macOS Plugins

The macOS plugin suite is auto-discovered from `plugins/`:

| Plugin | Example requests |
|---|---|
| `mac_calendar` | List upcoming events; create a calendar event |
| `mac_notes` | Search Notes; create a note |
| `mac_reminders` | List reminders; create a reminder |
| `mac_media` | Play, pause, skip, or change Music volume |
| `mac_system` | Read battery, uptime, Wi-Fi, and macOS version |
| `mac_clipboard` | Read or replace clipboard text |
| `mac_focus` | Toggle macOS Focus / Do Not Disturb |
| `mac_screenshot` | Save a timestamped screenshot to Desktop |
| `mac_notebooklm` | Open and control NotebookLM through your signed-in browser |
| `study_mode` | Student study sessions, flashcards, quizzes, deadlines, and focus (cross-platform) |

Actions that create, send, replace, toggle, or capture require explicit
confirmation in God Mode. Calendar, Notes, Reminders, Focus, and screenshot
plugins may prompt for macOS Automation, Accessibility, or Screen Recording
permissions the first time they are used.

NotebookLM uses the existing browser session, so sign in to Google yourself.
ADHITHIYA does not handle passwords or bypass Google authentication. Opening and
reading are available directly; asking questions or changing the page requires
God Mode confirmation.

### Student study mode

Ask ADHITHIYA to “study biology with me”, or use the auto-discovered
`study_mode` Gemini tool. It coordinates the existing plugins:

* `notebooklm` opens/reads NotebookLM or asks a question.
* `generate_flashcards` creates cards from supplied notes or NotebookLM text;
  cards are stored locally in `memory/study_flashcards.json`. Use
  `list_flashcards` and `review_flashcards` for retrieval practice.
* `start_quiz` creates an interactive quiz from supplied text, NotebookLM
  output, or supplied questions. `review_quiz` can grade supplied answers and
  `stop_quiz` clears the existing quiz panel.
* `deadline_create`/`deadline_list` use macOS Reminders by default, or Calendar
  when `use_calendar=true`.
* `focus` delegates to Pomodoro with `focus_action=start|stop|status|stats`.

ADHITHIYA previews persistent flashcard changes and requires `confirmed=true`
before saving, clearing, or recording a review. Creating a Reminder or Calendar
event also requires confirmation. NotebookLM uses only the already-authenticated
browser session; no password or authentication bypass is ever requested.

### Local Adaptive Learning

ADHITHIYA learns explicit corrections and preferences locally, and tracks which
tools succeed so future routing can improve. It does not rewrite its source code,
train on private audio, or store passwords and authentication codes. Learned
guidance is stored in `memory/long_term.json` and can be removed by deleting the
corresponding entries or resetting that file.

---

## 🆕 What's New in Mark LI

### 🧩 Plugin System — Extend JARVIS Without Touching a Single Core File
The headline feature of Mark LI, and the reason it's the final architecture version. Every new capability from now on ships as a single `.py` file:

1. Download a plugin file (e.g. `calorie_counter.py`)
2. Drop it into the `plugins/` folder
3. Restart JARVIS — done. The skill is live, by voice, in any language.

Each plugin declares its own Gemini tool schema and logic in one file. The engine auto-discovers it at startup, registers it with the Live session, and lists it in the new **🧩 Plugin Manager** panel where every plugin gets its own persistent ON/OFF toggle.

Safety is built in at three layers: a broken or badly written plugin can **never** crash JARVIS — it simply shows up as "BROKEN" in the manager with the error explained, while every other tool and plugin keeps working. Name collisions with core tools are detected and rejected automatically. Want to write your own? Copy `plugins/_template.py` and fill in two things: the `PLUGIN` dict and the `run()` function.

### 💓 Affective Dialog — JARVIS Hears How You Feel
Powered by Gemini Live's native audio understanding, JARVIS now picks up the emotion in your voice — excitement, frustration, fatigue — and adapts its own tone in response. Late-night tired questions get calm answers; excited announcements get energy back.

### 🤫 Proactive Audio — Knows When You're Not Talking to It
The biggest quality-of-life upgrade for an always-listening assistant: JARVIS can now tell when speech isn't addressed to it. Talking to someone in the room, taking a phone call, TV in the background — it stays silent instead of interjecting. No wake word needed, no accidental replies.

### ♾️ Unlimited Session Length — The Conversation Never Dies
Sliding-window context compression means the Live session no longer terminates when the context window fills up. Combined with session resumption, JARVIS holds one continuous conversation for hours without losing the thread.

All three Live API upgrades degrade gracefully: if the preview API ever rejects them, JARVIS automatically reconnects with the standard configuration — users never see a crash.

---

## 🗺️ Mark Roadmap

| Mark | Focus |
|---|---|
| **XLVIII** | Instant interrupt · parallel news · two-phase briefing · exponential backoff · vision cooldown |
| **XLIX** | Auto-start · clipboard intelligence · assistant customization |
| **L** | Session memory · background monitoring · proactive 2.0 · instant vision · parallel news search |
| **LI** | Plugin system · affective dialog · proactive audio · unlimited sessions |
| **LII+** | Plugin files: email · quiz mode · calorie counter · calendar · and more |

---

## ⚡ Quick Start

```bash
git clone https://github.com/FatihMakes/Mark-LI.git
cd Mark-LI
pip install -r requirements.txt
python main.py
```

> ⚠️ **Installation Note:** Some OS-specific dependencies are not bundled in `requirements.txt` to keep the repo lightweight. If you hit a `ModuleNotFoundError`, install the missing package with `pip install <module_name>`.

### macOS 12.7.6

On macOS, use the included launcher from the project directory:

```bash
chmod +x run_jarvis.sh
./run_jarvis.sh
```

When macOS asks, allow microphone, camera, Accessibility, and Screen Recording access
for the Python/Mark LI process in **System Preferences → Security & Privacy**.
The default assistant identity is **ADHITHIYA** and can be changed from the
customization panel.

### Optional local voice lock

Voice lock is disabled by default, preserving the existing Live mode. To turn
on the fail-closed gate, edit `config/api_keys.json`:

To launch ADHITHIYA automatically at macOS login, install the included
`com.adhithiya.assistant.plist` into `~/Library/LaunchAgents/`. Once a matching
local wake-word model is configured, saying **ADHITHIYA** wakes the protected
microphone without clicking the HUD.

For faster first responses, `fast_response` is enabled by default. It disables
the optional affective/proactive preview features while keeping normal Gemini
Live audio and tools:

```json
{ "fast_response": true }
```

```json
{
  "voice_lock_enabled": true,
  "wake_word_enabled": true,
  "wake_word": "ADHITHIYA",
  "wake_word_model_path": "/path/to/a/local/wake-word-model.onnx"
}
```

The default `ADHITHIYA` wake word needs a matching local openWakeWord model.
No model is downloaded automatically. An already-installed openWakeWord model,
an offline Vosk model directory, or a Porcupine `.ppn` model can be configured
with the corresponding backend settings. Porcupine requires an explicitly
configured `porcupine_access_key`; this project never asks for or invents one.

Install the optional local speaker backend and enroll once from the project
directory (the recording is held in memory only):

```bash
pip install -r requirements-voice-lock.txt
python -m core.voice_gate enroll
python -m core.voice_gate status
```

The profile is stored outside the source tree at
`~/.adhithiya/voice_profile.json` and contains only a Resemblyzer embedding and
metadata, never raw audio. Verification is a best-effort cosine-similarity
check, not biometric security. If the model, profile, or wake-word detector is
missing, protected audio is discarded and the UI reports the setup step;
Gemini is not sent microphone audio. Set `voice_lock_enabled` to `false` (and,
if needed, `wake_word_enabled` to `false`) to restore unrestricted Live mode.

#### Audio diagnostics and enrollment

Open **⚙ → Audio diagnostics** to choose an input device, watch a short
memory-only level meter, test the microphone/speaker, or enroll/clear the local
speaker profile. Enrollment audio is held in RAM only and is discarded after
the embedding is generated; `~/.adhithiya/voice_profile.json` contains an
embedding and metadata, not a recording. This is a convenience similarity
check, not biometric security. If no audio device or optional speaker model is
available, the panel reports the setup error without changing normal Live mode.

The application also provides a macOS 12-compatible `QSystemTrayIcon` menu for
show/hide, microphone mute, quit, and launch-at-login status. Closing the
window hides it when a tray is available; use **Quit ADHITHIYA** to stop the
process.

### God Mode

God Mode enables decisive routine automation. For safety, ADHITHIYA still asks
for explicit confirmation before deleting files, sending messages, cleaning the
desktop, restarting, or shutting down the Mac. Confirmed actions are executed
with `confirmed=true`.

### Project Agent Mode (opt-in)

Project Agent Mode is a local safety boundary for project work. It can plan,
apply complete file edits, and run tests through the `project_agent` tool (or
`/agent plan <goal>` and `/agent status` in the text box). Normal chat and the
existing tools are unchanged. It is disabled by default; opt in explicitly:

```json
{
  "agent_mode": {
    "enabled": true,
    "workspace_root": "/path/to/the/parent/workspace",
    "self_recovery": {
      "enabled": true,
      "max_attempts": 2,
      "timeout": 30
    }
  }
}
```

The current application directory is always the project root. Relative paths
are confined to the configured workspace, and commands are parsed without a
shell from a small allowlist (`python`, `pytest`, `unittest`, `ruff`, `mypy`,
`git`, and related developer runners). Shell operators, shell interpreters,
inline code, and paths outside the workspace are rejected. Destructive or
network commands, external actions, and edits outside the project root pause
in `awaiting_approval`; repeat the exact request with `confirmed=true` to
continue. External actions are described only and are never silently performed.

When Agent Mode pauses for approval, the **⚙ → Agent Mode** panel shows the
pending request and live progress. Use **APPROVE** to run the exact request or
**REJECT** to discard it; normal chat remains unchanged.

### Bounded self-recovery

When an opted-in project command (or a project-oriented plugin command) fails,
ADHITHIYA records a redacted, structured obstacle, searches local README/docs,
and may try up to `max_attempts` safe alternatives. Every alternative is
validated by the same no-shell command allowlist and has its own timeout.
Network, destructive, authentication, device-wide, and external actions are
never run automatically: the exact action is shown in the Agent Mode panel and
requires approval. Successful procedure metadata is stored locally in
`memory/recovery_procedures.json`; raw error output and secrets are not stored.

Use `project_agent` with `operation: "status"` to see recovery progress, or
`operation: "reset"` (also `/agent reset`) to clear status and learned procedures.

---

## 📋 Requirements

| Requirement | Details |
| --- | --- |
| **OS** | Windows 10/11, macOS, or Linux |
| **Python** | 3.11 or 3.12 |
| **Microphone** | Required for voice interaction |
| **API Key** | Free Gemini API key (`config/api_keys.json`) |

---

## 🗂️ Project Structure

```
Mark LI/
├── main.py                   # Core loop — Gemini Live session, audio I/O, tool dispatch
├── ui.py                     # PyQt6 HUD — waveform, log panel, plugin manager, camera feed
├── setup.py                  # First-run configuration wizard
├── plugins/
│   └── _template.py          # Copy this to write a new plugin — one file, drop in, done
├── actions/
│   ├── web_search.py         # Gemini + DDG parallel search (news, research, price, compare)
│   ├── screen_processor.py   # Screen capture & webcam vision via Gemini Live
│   ├── background_monitor.py # User-configured topic watching — daily DDG check, no crypto
│   ├── proactive.py          # Proactive 2.0 — time/context/rotation-aware check-ins
│   ├── reminder.py           # OS-native scheduled notifications
│   ├── system_monitor.py     # CPU / RAM / GPU / temperature telemetry
│   ├── computer_settings.py  # Volume, brightness, WiFi, power
│   ├── computer_control.py   # Keyboard shortcuts, mouse, window management
│   ├── open_app.py           # Application launcher
│   ├── browser_control.py    # Web browser control
│   ├── file_controller.py    # File system operations
│   ├── file_processor.py     # Document reading and summarization
│   ├── send_message.py       # Messaging integration
│   ├── weather_report.py     # Live weather data
│   ├── flight_finder.py      # Flight search
│   ├── youtube_video.py      # YouTube playback control
│   ├── game_updater.py       # Game update management (Steam / Epic)
│   ├── code_helper.py        # Code review and generation
│   ├── dev_agent.py          # Developer task agent
│   └── desktop.py            # Desktop and taskbar control
├── memory/
│   ├── memory_manager.py     # Load/save long_term.json — sessions, monitors, identity
│   └── long_term.json        # Persistent store: identity, preferences, projects, sessions, monitors
├── core/
│   ├── prompt.txt            # Assistant personality and tool-routing rules
│   ├── voice_gate.py         # Optional local wake-word + speaker gate
│   ├── plugin_loader.py      # Plugin engine — discovery, validation, crash isolation
│   ├── project_agent.py      # Opt-in bounded Agent Mode and command policy
│   └── self_recovery.py      # Bounded local failure recovery and procedure memory
└── config/
    └── api_keys.json         # API key, OS setting, assistant name, user name
```

---

## ⚠️ License

Personal and non-commercial use only.
Licensed under **[Creative Commons BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)**.

---

## 👤 Connect with the Creator

Engineered by a developer building a real-world JARVIS-style assistant.
⭐ **Star the repository to support the journey to Mark 100.**

| Platform | Link |
| --- | --- |
| YouTube | [@FatihMakes](https://www.youtube.com/@FatihMakes) |
| Instagram | [@fatihmakes](https://www.instagram.com/fatihmakes) |
