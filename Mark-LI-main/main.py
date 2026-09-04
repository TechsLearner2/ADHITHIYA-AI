import platform as _platform
import subprocess as _subprocess
import sys

# ── Make stdout/stderr UTF-8 tolerant ────────────────────────────────────────
# On non-UTF-8 Windows consoles (cp1254/cp1252/cp936...) any print() containing
# an emoji raises UnicodeEncodeError.  Several of those prints sit inside except
# handlers, so the handler itself would blow up and skip the recovery code that
# follows it — turning a recoverable error into a silent hang.  errors="replace"
# makes every print safe.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass   # frozen builds may have no real stream attached

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **                       kw)

    _subprocess.Popen = _Popen

# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import concurrent.futures
import re
import threading
import time
import json
import traceback
from datetime import datetime
from pathlib import Path

import sounddevice as sd
from ui import AdhithiyaUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    save_session_summary, pop_last_session,
)
from memory.adaptive_learning import (
    learn_from_user_text, record_tool_outcome, format_learning_for_prompt,
)
from memory.self_learning import (
    learn_from_failure, format_learned_for_prompt,
)

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import _capture_camera, _capture_screen
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from actions.web_search        import _news as _fetch_news_sync
from actions.web_fetch         import web_fetch as web_fetch_action
from actions.image_generate    import image_generate as image_generate_action
from core.task_runner          import run_task as run_task_agent
from memory.config_manager     import (
    get_brief_enabled, get_agent_workspace_root,
    get_self_recovery_config, get_data_dir, default_agent_workspace_root,
)
from memory.config_manager     import DEFAULT_ASSISTANT_NAME
from core.plugin_loader        import discover_plugins, USER_PLUGINS_DIR, USER_PLUGINS_PREFIX
from core.plugin_builder       import run as plugin_builder_run
from core.project_agent       import AgentResult, ProjectAgent
from core.self_recovery       import SelfRecovery
from core.voice_gate           import VoiceGate

def get_base_dir():
    if getattr(sys, "frozen", False):
        # PyInstaller: bundled assets (prompt.txt, plugins, face.png) live in
        # sys._MEIPASS, not next to the executable.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _plugin_commands(args: dict) -> tuple[str, ...]:
    values = []
    for key in ("command", "commands", "tests"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, (list, tuple)):
            values.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
    return tuple(values)


def _plugin_failure_is_recoverable(name: str, args: dict, result: object) -> bool:
    """Only recover plugin failures that explicitly describe project commands."""
    text = str(result).lower()
    if not any(marker in text for marker in ("failed", "error", "timed out", "not installed")):
        return False
    return bool(_plugin_commands(args) or any(key in args for key in ("goal", "task")))

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = get_data_dir() / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024
AUDIO_INPUT_QUEUE_LIMIT = 40
OUTPUT_BLOCKSIZE      = 512      # explicit small output buffer (~21 ms @ 24 kHz)
DEFAULT_PREBUFFER_MS  = 80       # jitter cushion before playback starts each turn
MAX_BATCH_BYTES       = 4800     # ~100 ms @ 24 kHz / 16-bit mono per write

def _get_api_key() -> str:
    from core.llm import get_api_key
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "config/api_keys.json is missing an API key — run the app once and "
            "enter your key (free Groq key from console.groq.com, or an OpenAI key)."
        )
    return key


class _FR:
    """Tool-result carrier passed back to _execute_tool as `fr.response`."""
    __slots__ = ("id", "name", "response")
    def __init__(self, id, name, response):
        self.id = id
        self.name = name
        self.response = response



def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            f"You are {DEFAULT_ASSISTANT_NAME}, a cinematic onboard AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics — always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": (
            "Sends a text message via WhatsApp, Telegram, or another platform. "
            "This is an external side effect: require the user's explicit confirmation "
            "before calling with confirmed=true."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."},
                "confirmed":    {"type": "BOOLEAN", "description": "Set true only after the user explicitly confirms sending this exact message."},
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when user says: close camera, stop camera, turn off the camera, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."},
                "confirmed":   {"type": "BOOLEAN", "description": "Set true only after the user explicitly confirms a restart or shutdown."},
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Simple open/search requests launch the user's own browser normally (their real profile "
            "and logged-in accounts); interactive actions (click, type, fill_form...) attach an "
            "automation browser. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
                "confirmed":   {"type": "BOOLEAN", "description": "Set true only after the user explicitly confirms deletion."},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "confirmed": {"type": "BOOLEAN", "description": "Set true only after the user explicitly confirms a destructive cleanup."},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use browser_control or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "manage_monitor",
        "description": (
            "Add, remove, or list background monitoring topics. "
            "ADHITHIYA checks these topics once a day and alerts the user when there is a new development. "
            "Use 'add' when the user says 'monitor X', 'track X', 'follow X'. "
            "Use 'remove' when the user says 'stop monitoring X'. "
            "Use 'list' when the user asks what is being monitored. "
            "Do NOT add crypto, financial, or trading topics."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type":        "STRING",
                    "description": "add | remove | list",
                },
                "topic": {
                    "type":        "STRING",
                    "description": "Topic to monitor or stop monitoring (e.g. 'space exploration', 'AI news')",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "shutdown_adhithiya",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop ADHITHIYA. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Alex, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "project_agent",
        "description": (
            "Project work on the current project. Use it for a concrete "
            "multi-step project plan, bounded file edits, and validated tests. "
            "Operations: plan, execute, test, status, or reset. Pass edits as path/content "
            "objects and commands/tests as lists. The local safety policy rejects "
            "shell syntax, confines paths to the workspace, and asks for "
            "confirmed=true before destructive, network, external, or outside-project actions."
            " Failed project commands may use bounded local self-recovery; use status "
            "or reset to inspect or clear its progress and learned procedures."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "operation": {"type": "STRING", "description": "plan | execute | test | status | reset"},
                "goal": {"type": "STRING", "description": "Project goal or change description"},
                "edits": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "path": {"type": "STRING", "description": "Project-relative file path"},
                            "content": {"type": "STRING", "description": "Complete replacement file content"},
                        },
                    },
                },
                "commands": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Validated project commands to run without a shell",
                },
                "tests": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Validated test commands to run after edits",
                },
                "external_actions": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "External actions to describe; never run silently",
                },
                "confirmed": {
                    "type": "BOOLEAN",
                    "description": "Explicit approval for the exact pending action",
                },
            },
            "required": [],
        },
    },
    {
        "name": "plugin_builder",
        "description": (
            "Write a NEW ability (plugin) for ADHITHIYA when no existing tool or "
            "plugin can do what the user asks. Action 'build' drafts the plugin "
            "(goal describes what it should do; name is optional), shows a preview, "
            "and — only after the user explicitly confirms with confirmed=true — "
            "installs it and makes it live immediately. Action 'list' shows the "
            "abilities that were built; action 'remove' (confirmed=true) deletes "
            "one ADHITHIYA built. Never install or remove without the user's "
            "explicit confirmation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "build | list | remove"},
                "goal": {"type": "STRING", "description": "What the new ability should do, in one or two sentences."},
                "name": {"type": "STRING", "description": "Optional snake_case name for the new ability."},
                "confirmed": {"type": "BOOLEAN", "description": "Set true only after the user explicitly approved installing or removing."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "run_task",
        "description": (
            "Autonomous multi-step task engine. Give it ONE goal and it plans and "
            "executes up to 8 steps by itself — searching the web, fetching pages, "
            "reading/writing files in its workspace, running safe developer "
            "commands (python, pytest, git), setting reminders, checking "
            "calendar/notes, and generating images — then reports a summary. Use "
            "this for any job that needs several steps: research and summarize, "
            "debug and fix code, draft a document, plan the day. It cannot delete "
            "files, send messages, or restart — those still need confirmation "
            "through their normal tools."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal": {"type": "STRING", "description": "The single goal to accomplish, in one or two sentences."},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch a web page and return its key content as readable text. Use "
            "for deep reading: open an article/URL and summarize its actual "
            "content instead of guessing from search snippets."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Full http(s) URL to fetch."},
            },
            "required": ["url"],
        },
    },
    {
        "name": "image_generate",
        "description": (
            "Generate an image from a text prompt with OpenAI and save it "
            "to the Pictures/ADHITHIYA folder. Use when the user asks to create, "
            "draw, or imagine an image, wallpaper, or concept art."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt": {"type": "STRING", "description": "Detailed image description."},
            },
            "required": ["prompt"],
        },
    },
]

class AdhithiyaAssistant:

    def __init__(self, ui: AdhithiyaUI):
        self.ui             = ui
        self._asst_name     = DEFAULT_ASSISTANT_NAME   # updated each session from config
        self.audio_in_queue       = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_agent_approve  = self._approve_pending_agent
        self.ui.on_agent_reject   = self._reject_pending_agent
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._session_log: list[str] = []          # conversation turns for end-of-session summary
        # Optional fail-closed local gate.  It performs no model loading until
        # the first protected audio frame and is disabled by default so the
        # existing unrestricted Live mode remains the fallback.
        self._voice_gate = VoiceGate.from_config_path(API_CONFIG_PATH)
        # Dedicated executor for blocking sounddevice writes so audio playback
        # never has to wait behind slow tool calls on the shared default executor.
        self._audio_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="audio"
        )
        _agent_workspace = get_agent_workspace_root(default_agent_workspace_root())
        _recovery_config = get_self_recovery_config()
        self._project_agent = ProjectAgent(
            workspace_root=_agent_workspace,
            project_root=BASE_DIR,
            enabled=True,
            recovery=SelfRecovery(
                _agent_workspace,
                BASE_DIR,
                enabled=_recovery_config["enabled"],
                max_attempts=_recovery_config["max_attempts"],
                timeout=_recovery_config["timeout"],
                progress=lambda msg: (self.ui.write_log(f"[Agent] {msg}"),
                                      self.ui.agent_progress(msg)),
            ),
            progress=lambda msg: (self.ui.write_log(f"[Agent] {msg}"),
                                  self.ui.agent_progress(msg)),
        )

        self._prebuffer_ms    = DEFAULT_PREBUFFER_MS   # overridden from config in _build_system_prompt()
        self._output_blocksize = OUTPUT_BLOCKSIZE
        self._owner_name      = ""   # resolved in _build_system_prompt() (config → memory fallback)
        # Self-learning: dedup + cooldown so a single problem is researched once
        # per session instead of spamming searches in a retry loop.
        self._learned_this_session: set[str] = set()
        self._learn_cooldown_until = 0.0
        _core_names = {t["name"] for t in TOOL_DECLARATIONS}
        self._plugin_registry = discover_plugins(
            plugins_dir=get_base_dir() / "plugins",
            core_tool_names=_core_names,
            logger=lambda msg: (print(f"[Plugins] {msg}"), self.ui.write_log(f"SYS: {msg}")),
            extra_dirs=[(USER_PLUGINS_DIR, USER_PLUGINS_PREFIX)],
        )
        self.ui.get_plugins = self._plugin_registry.list_for_ui
        self.ui.request_say = self.plugin_say   # plugins: mid-task speech channel

    def plugin_say(self, instruction: str) -> None:
        """Thread-safe speech channel for plugins: speak a short line while the
        plugin's run() is still executing."""
        self.speak(instruction)

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    def _maybe_learn(self, name: str, args: dict, error: object) -> None:
        """
        Self-learning: when a tool fails, research the fix online in the
        background and remember it. On success the guidance is injected into the
        Live session so ADHITHIYA can immediately explain and offer to retry.

        Guarded by a per-session dedup set + cooldown so a retry loop can never
        turn into a search storm. Fire-and-forget — never blocks the turn.
        """
        try:
            now = time.monotonic()
            if now < self._learn_cooldown_until:
                return
            key = f"{name}::{str(error)[:80]}"
            if key in self._learned_this_session:
                return
            self._learned_this_session.add(key)
            self._learn_cooldown_until = now + 20.0

            loop = self._loop
            if not loop:
                return
            self.ui.write_log(f"LEARN: '{name}' failed — researching how to fix it…")

            async def _do():
                try:
                    guidance = await asyncio.to_thread(
                        learn_from_failure, name, args, str(error)
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[Learn] background research error: {exc}")
                    return
                if not guidance:
                    self.ui.write_log(f"LEARN: nothing usable found for '{name}'.")
                    return
                self.ui.write_log(f"LEARN: fix remembered for '{name}'.")
                self.speak(
                    f"I worked out how to do '{name}' correctly and I'll remember it."
                )

            asyncio.run_coroutine_threadsafe(_do(), loop)
        except Exception:  # noqa: BLE001 - learning is best-effort
            pass

    def _on_text_command(self, text: str):
        if not self._loop:
            return
        # Normal text goes through the OpenAI chat turn. Only an explicit /agent
        # command is handled locally, so existing chat behavior is unchanged.
        stripped = text.strip()
        lowered = stripped.lower()
        if lowered in {"/agent status", "/agent reset"} or lowered.startswith("/agent plan "):
            if lowered == "/agent status":
                params = {"operation": "status"}
            elif lowered == "/agent reset":
                params = {"operation": "reset"}
            else:
                params = {"operation": "plan", "goal": stripped[12:].strip()}

            async def _run_local_agent():
                self._project_agent.enabled = True
                self._project_agent.recovery.enabled = get_self_recovery_config()["enabled"]
                self._project_agent.workspace_root = get_agent_workspace_root(default_agent_workspace_root())
                result = await asyncio.to_thread(self._project_agent.handle, params)
                self.ui.write_log(f"[Agent] {result.as_text()}")
                self.ui.show_agent_result(result)
                self.speak(result.as_text())

            asyncio.run_coroutine_threadsafe(_run_local_agent(), self._loop)
            return
        async def _do():
            try:
                answer = await self._chat_turn(stripped)
            except Exception as e:
                print(f"[ADHITHIYA] Turn error: {e}")
                self.ui.write_log(f"ERR: {e}")
                answer = ("Sorry — I hit a problem reaching the AI brain. "
                          "Check your connection and try again.")
            if answer:
                await self._speak_text(answer)
        asyncio.run_coroutine_threadsafe(_do(), self._loop)

    def _approve_pending_agent(self) -> None:
        """Run the exact pending project request from the UI approval button."""
        if not self._loop:
            return
        async def _approve():
            result = await asyncio.to_thread(self._project_agent.approve_pending)
            self.ui.show_agent_result(result)
            self.ui.write_log(f"[Agent] {result.as_text()}")
            self.speak(result.as_text())
        asyncio.run_coroutine_threadsafe(_approve(), self._loop)

    def _reject_pending_agent(self) -> None:
        """Discard the pending project request without changing files."""
        if not self._loop:
            return
        async def _reject():
            result = await asyncio.to_thread(self._project_agent.reject_pending)
            self.ui.show_agent_result(result)
            self.ui.write_log(f"[Agent] {result.as_text()}")
        asyncio.run_coroutine_threadsafe(_reject(), self._loop)

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def interrupt(self) -> None:
        """Stop ADHITHIYA mid-speech: drain queued audio and open mic immediately."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[ADHITHIYA] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        """Queue text to be spoken aloud via TTS (thread-safe, non-blocking)."""
        loop = getattr(self, "_loop", None)
        if not loop or not (text or "").strip():
            return

        async def _put():
            try:
                self._speak_queue.put_nowait(text)
            except asyncio.QueueFull:
                pass
        try:
            asyncio.run_coroutine_threadsafe(_put(), loop)
        except Exception:
            pass

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_system_prompt(self) -> str:
        from datetime import datetime

        # Load customization from config
        try:
            _cfg = json.loads(open(API_CONFIG_PATH, encoding="utf-8").read())
            self._asst_name = (_cfg.get("assistant_name") or DEFAULT_ASSISTANT_NAME).strip()
            _user_name = (_cfg.get("user_name") or "").strip()
            try:
                self._prebuffer_ms = max(0, min(1000, int(_cfg.get("audio_prebuffer_ms", DEFAULT_PREBUFFER_MS))))
            except (TypeError, ValueError):
                self._prebuffer_ms = DEFAULT_PREBUFFER_MS
            try:
                self._output_blocksize = max(0, min(4096, int(_cfg.get("audio_blocksize", OUTPUT_BLOCKSIZE))))
            except (TypeError, ValueError):
                self._output_blocksize = OUTPUT_BLOCKSIZE
        except Exception:
            self._asst_name = DEFAULT_ASSISTANT_NAME
            _user_name = ""
            self._prebuffer_ms = DEFAULT_PREBUFFER_MS
            self._output_blocksize = OUTPUT_BLOCKSIZE

        memory     = load_memory()
        # The owner's name lives in config; if it was never set there, fall back
        # to what ADHITHIYA learned in conversation (memory identity/name) so it
        # keeps recognising the same person across sessions.
        if not _user_name:
            _mem_ident = memory.get("identity") or {}
            _mem_name = _mem_ident.get("name") or {}
            _mem_val = _mem_name.get("value") if isinstance(_mem_name, dict) else _mem_name
            _user_name = str(_mem_val or "").strip()
        mem_str    = format_memory_for_prompt(memory)
        learning_str = format_learning_for_prompt(memory)
        learned_str  = format_learned_for_prompt()
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        # Identity injection — overrides any hardcoded name in prompt.txt
        self._owner_name = _user_name
        if _user_name:
            _addr = (f"ADDRESS: The user is '{_user_name}' — your owner and primary "
                     f"user. You know them personally; call them by name, warmly.")
        else:
            _addr = ("ADDRESS: You don't know the user's name yet. On your first "
                     "greeting, ask what to call them; when they answer, save it with "
                     "save_memory (category='identity', key='name'). Until then address "
                     "them respectfully as \"sir\". Never mix languages.")
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. "
            f"Always refer to yourself as {self._asst_name}.\n"
            f"The person speaking to you is your owner. Recognise them as the same "
            f"person across sessions — greet them personally, remember what they tell "
            f"you about themselves, and never treat them like a stranger.\n"
            f"{_addr}\n\n"
        )

        # One nature, no modes — ADHITHIYA is always this way. Decisive routine
        # automation by default; confirmation is required only before
        # irreversible or external actions.
        nature_ctx = (
            "[OPERATING NATURE]\n"
            "You are always decisive: execute every routine task immediately — "
            "open apps, search, control the computer, manage files, set "
            "reminders — without asking. The ONLY times you pause for explicit "
            "confirmation are irreversible or external actions: deleting files, "
            "cleaning the desktop, sending messages, restarting, or shutting "
            "down. State exactly what you will do, then call the tool with "
            "confirmed=true only after the user confirms. Never treat silence "
            "or an unrelated 'yes' as confirmation.\n\n"
        )

        parts = [time_ctx, identity_ctx, nature_ctx]
        if mem_str:
            parts.append(mem_str)
        if learning_str:
            parts.append(learning_str)
        if learned_str:
            parts.append(learned_str)
        parts.append(sys_prompt)
        return "\n".join(parts)

    def _openai_tools(self) -> list[dict]:
        """All tool declarations (core + plugins) in OpenAI function format."""
        from core.llm import to_openai_tools
        return to_openai_tools(TOOL_DECLARATIONS + self._plugin_registry.get_tool_declarations())


    async def _execute_tool(self, fc):
        name = fc.name
        args = dict(fc.args or {})

        print(f"[ADHITHIYA] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            record_tool_outcome(name, True)
            return _FR(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            confirmation = self._confirmation_required(name, args)
            if confirmation and not self._is_confirmed(args):
                result = (
                    f"Confirmation required before I can {confirmation}. "
                    "Ask the user to confirm this exact action, then call the same tool "
                    "again with confirmed=true."
                )
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")
                return _FR(
                    id=fc.id, name=name, response={"result": result}
                )

            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                        print(f"[Vision] 🖥️  Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"The image is attached to your next message — describe it now."
                    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "project_agent":
                self._project_agent.enabled = True
                self._project_agent.recovery.enabled = get_self_recovery_config()["enabled"]
                self._project_agent.workspace_root = get_agent_workspace_root(default_agent_workspace_root())
                agent_result = await asyncio.to_thread(self._project_agent.handle, args)
                self.ui.show_agent_result(agent_result)
                result = agent_result.as_text()

            elif name == "plugin_builder":
                r = await loop.run_in_executor(
                    None,
                    lambda: plugin_builder_run(args, self._plugin_registry, self.ui),
                )
                result = r or "Done."

            elif name == "run_task":
                r = await loop.run_in_executor(
                    None, lambda: run_task_agent(str(args.get("goal", "")), self.ui))
                result = r or "Done."

            elif name == "web_fetch":
                r = await loop.run_in_executor(None, lambda: web_fetch_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "image_generate":
                r = await loop.run_in_executor(None, lambda: image_generate_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
                # Mirror results to the on-screen content panel
                _mode = args.get("mode", "search")
                if r and not r.startswith("No results") and not r.startswith("Search failed"):
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            elif name == "shutdown_adhithiya":
                self.ui.write_log("SYS: Shutdown requested.")
                async def _do_shutdown():
                    await self._save_session_summary()
                    try:
                        farewell = await self._chat_turn(
                            "Say a brief natural goodbye to the user.", log_as_user=False)
                        if farewell:
                            await self._speak_text(farewell)
                    except Exception:
                        pass
                    await asyncio.sleep(1.5)
                    self._audio_executor.shutdown(wait=False)
                    self.ui.quit()
                asyncio.create_task(_do_shutdown())

            else:
                if self._plugin_registry.has(name):
                    r = await loop.run_in_executor(
                        None,
                        lambda: self._plugin_registry.run(name, args, player=self.ui, session_memory=None)
                    )
                    result = r or "Done."
                    self._project_agent.recovery.enabled = get_self_recovery_config()["enabled"]
                    if _plugin_failure_is_recoverable(name, args, result):
                        recovery = await asyncio.to_thread(
                            self._project_agent.recover_tool_failure,
                            name,
                            result,
                            goal=str(args.get("goal") or args.get("task") or name),
                            original_commands=_plugin_commands(args),
                        )
                        if recovery.status != "no_candidates":
                            if recovery.status == "awaiting_approval":
                                self.ui.show_agent_result(AgentResult(
                                    self._project_agent.state,
                                    recovery.as_text(),
                                    approval_id=recovery.approval_id,
                                ))
                            result = f"{result}\n{recovery.as_text()}"
                else:
                    result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)
            record_tool_outcome(name, False)
            self._maybe_learn(name, args, e)
        else:
            ok = not str(result).lower().startswith(
                ("could not", "error", "failed", "unknown", "please confirm")
            )
            record_tool_outcome(name, ok)
            if not ok:
                self._maybe_learn(name, args, result)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[ADHITHIYA] 📤 {name} → {str(result)[:80]}")
        return _FR(
            id=fc.id, name=name,
            response={"result": result}
        )

    @staticmethod
    def _is_confirmed(args: dict) -> bool:
        value = args.get("confirmed", False)
        return value is True or str(value).strip().lower() in {"true", "yes", "1", "confirm"}

    @staticmethod
    def _confirmation_required(name: str, args: dict) -> str | None:
        if name == "send_message":
            return f"send this message to {args.get('receiver', 'the recipient')}"
        if name == "file_controller" and str(args.get("action", "")).lower().strip() == "delete":
            return f"move {args.get('name') or args.get('path', 'this item')} to the Trash"
        if name == "computer_settings":
            action = str(args.get("action", "")).lower().strip().replace("-", "_").replace(" ", "_")
            if action in {"restart", "shutdown"}:
                return f"{action} the computer"
        if name == "desktop_control":
            action = str(args.get("action", "")).lower().strip()
            if action == "clean":
                return "clean the desktop"
        return None

    # ── Voice pipeline (mic → Whisper → LLM + tools → TTS → speakers) ─────────

    def _on_voice_gate_notice(self, message: str) -> None:
        """Display local gate state without sending the gated audio upstream."""
        self.ui.write_log(f"VOICE: {message}")

    def _mic_loop(self) -> None:
        """Background thread: capture mic PCM, detect speech, transcribe, and
        hand finished transcripts to the async conversation loop."""
        loop = self._loop
        try:
            stream = sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=0,
                latency="low",
                device=getattr(self.ui, "audio_input_device", None),
            )
            stream.start()
        except Exception as e:
            print(f"[ADHITHIYA] ❌ Mic: {e}")
            return

        buf = bytearray()
        in_speech = False
        last_speech = time.monotonic()

        def _rms(b: bytes) -> float:
            if not b:
                return 0.0
            try:
                import numpy as np
                arr = np.frombuffer(b, dtype=np.int16).astype(np.float32)
                if arr.size == 0:
                    return 0.0
                return float(np.sqrt(np.mean(arr * arr)))
            except Exception:
                return 0.0

        try:
            while True:
                chunk, _overflowed = stream.read(CHUNK_SIZE)
                with self._speaking_lock:
                    speaking = self._is_speaking
                if speaking or self.ui.muted or self._phone_active:
                    buf.clear()
                    in_speech = False
                    continue

                data = chunk.tobytes()
                decision = None
                try:
                    decision = self._voice_gate.process_audio(data)
                except (TypeError, ValueError, RuntimeError) as exc:
                    loop.call_soon_threadsafe(
                        self._on_voice_gate_notice, f"Voice gate stopped audio: {exc}")
                if decision and decision.message:
                    loop.call_soon_threadsafe(self._on_voice_gate_notice, decision.message)
                if decision and decision.state == "verified":
                    _who = f"it's you, {self._owner_name}" if self._owner_name else "it's you"
                    loop.call_soon_threadsafe(
                        self._on_voice_gate_notice, f"Voice matched — {_who}.")
                if decision is None or not decision.accepted:
                    continue

                if _rms(data) > 300.0:
                    if not in_speech:
                        buf.clear()
                        in_speech = True
                    buf.extend(data)
                    last_speech = time.monotonic()
                elif in_speech:
                    buf.extend(data)
                    if time.monotonic() - last_speech > 0.8:
                        pcm = bytes(buf)
                        buf.clear()
                        in_speech = False
                        if len(pcm) >= SEND_SAMPLE_RATE:  # at least ~1 s of speech
                            self._finalize_speech(pcm)
        except Exception as e:
            print(f"[ADHITHIYA] ❌ Mic loop: {e}")
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _finalize_speech(self, pcm: bytes) -> None:
        """Transcribe a finished utterance and queue it for the conversation loop."""
        loop = self._loop

        def _transcribe() -> str:
            try:
                from core.llm import transcribe_wav
                return transcribe_wav(self._pcm_to_wav(pcm, SEND_SAMPLE_RATE))
            except Exception as e:
                print(f"[ADHITHIYA] ❌ Transcribe: {e}")
                return ""

        async def _do():
            text = (await asyncio.to_thread(_transcribe) or "").strip()
            if text:
                self._last_user_speech = time.monotonic()
                try:
                    self._transcript_queue.put_nowait(text)
                except asyncio.QueueFull:
                    pass

        try:
            asyncio.run_coroutine_threadsafe(_do(), loop)
        except Exception:
            pass

    @staticmethod
    def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        return buf.getvalue()

    @staticmethod
    def _wav_to_pcm(wav: bytes, target_rate: int) -> bytes:
        """Decode a WAV blob and resample to target_rate Hz mono int16."""
        import io
        import wave
        try:
            import numpy as np
        except Exception:
            return b""
        try:
            with wave.open(io.BytesIO(wav), "rb") as w:
                rate = w.getframerate()
                ch = w.getnchannels()
                raw = w.readframes(w.getnframes())
                data = np.frombuffer(raw, dtype=np.int16)
            if ch > 1:
                data = data.reshape(-1, ch).mean(axis=1).astype(np.int16)
            if rate != target_rate and len(data) > 0:
                ratio = target_rate / rate
                n_out = int(len(data) * ratio)
                idx = (np.arange(n_out) / ratio).astype(np.int32)
                idx = np.clip(idx, 0, len(data) - 1)
                data = data[idx]
            return data.astype(np.int16).tobytes()
        except Exception as e:
            print(f"[Audio] WAV decode failed: {e}")
            return b""

    @staticmethod
    def _image_data_url(img_b: bytes, mime: str) -> str:
        import base64 as _b64
        return f"data:{mime};base64,{_b64.b64encode(img_b).decode('ascii')}"

    async def _chat_turn(self, user_text: str, log_as_user: bool = True) -> str:
        """Run one conversation turn: LLM + tool loop (+ vision). Returns the
        final text answer to speak."""
        from core.llm import chat, chat_with_image, provider
        user_text = (user_text or "").strip()
        if not user_text:
            return ""

        if log_as_user:
            self._last_user_speech = time.monotonic()
            self.ui.write_log(f"You: {user_text}")
            self._session_log.append(f"User: {user_text}")
            learn_from_user_text(user_text)
            if self._dashboard:
                asyncio.create_task(self._dashboard.broadcast({
                    "type": "log", "speaker": "user", "text": user_text,
                    "ts": datetime.now().isoformat(),
                }))

        system_prompt = await asyncio.to_thread(self._build_system_prompt)
        self._chat_history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": system_prompt}] + list(self._chat_history[-30:])
        tools = self._openai_tools()

        for _ in range(8):
            resp = await asyncio.to_thread(chat, messages, tools)
            tool_calls = resp.get("tool_calls") or []
            if not tool_calls:
                answer = resp.get("text", "").strip()
                if answer:
                    self._chat_history.append({"role": "assistant", "content": answer})
                if self._vision_cam_active:
                    self._vision_cam_active = False
                    self.ui.stop_camera_stream()
                return answer

            tool_results = []
            for tc in tool_calls:
                name = tc.get("name", "")
                args = dict(tc.get("arguments") or {})
                shim = type("FC", (), {"id": tc.get("id", "call"), "name": name, "args": args})()
                fr = await self._execute_tool(shim)
                result_text = str((fr.response or {}).get("result", "Done."))
                tool_results.append((name, args, result_text))
                print(f"[ADHITHIYA] 📞 {name} {args}")

            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {"name": tc.get("name", ""),
                                 "arguments": json.dumps(tc.get("arguments") or {})},
                } for i, tc in enumerate(tool_calls)],
            })
            for i, (_n, _a, result_text) in enumerate(tool_results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_calls[i].get("id", f"call_{i}"),
                    "content": result_text,
                })

            # Vision injection: screen_process captured an image — ask about it
            if self._pending_vision:
                img_b, mime_t, question, angle = self._pending_vision
                self._pending_vision = None
                self._vision_busy = False
                if self._vision_cam_active:
                    self._vision_cam_active = False
                    self.ui.stop_camera_stream()
                if provider() == "groq":
                    # Groq's text chat model can't see images — run the vision
                    # model separately and feed its description back as text.
                    desc = await asyncio.to_thread(
                        chat_with_image, question or "What do you see?", img_b, mime_t)
                    messages.append({"role": "user", "content": (
                        f"[Vision] You captured an image. The vision model described it as: "
                        f"{desc}\nNow answer the user's original request based on that description."
                    )})
                else:
                    print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle})")
                    messages.append({"role": "user", "content": [
                        {"type": "text", "text": question or "What do you see?"},
                        {"type": "image_url", "image_url": {"url": self._image_data_url(img_b, mime_t)}},
                    ]})

        return "I couldn't complete that task."

    async def _speak_text(self, text: str) -> None:
        """Synthesise and play a text answer, relaying to connected phones."""
        text = (text or "").strip()
        if not text:
            return
        self.ui.write_log(f"{self._asst_name}: {text}")
        self._session_log.append(f"{self._asst_name}: {text}")
        if self._dashboard:
            asyncio.create_task(self._dashboard.broadcast({
                "type": "log", "speaker": "adhithiya", "text": text,
                "ts": datetime.now().isoformat(),
            }))

        def _synthesize():
            from core.llm import tts_wav
            return tts_wav(text)

        try:
            wav = await asyncio.to_thread(_synthesize)
        except Exception as e:
            print(f"[ADHITHIYA] ❌ TTS: {e}")
            return

        pcm = await asyncio.to_thread(self._wav_to_pcm, wav, RECEIVE_SAMPLE_RATE)
        if not pcm:
            return

        self._interrupted = False
        while True:                       # drop any audio still queued
            try:
                self.audio_in_queue.get_nowait()
            except Exception:
                break
        self._turn_done_event.clear()
        for i in range(0, len(pcm), 2400):
            try:
                self.audio_in_queue.put_nowait(pcm[i:i + 2400])
            except asyncio.QueueFull:
                break
        if self._dashboard and self._dashboard.has_clients():
            asyncio.create_task(self._dashboard.broadcast_audio(pcm))
        self._turn_done_event.set()

    async def _speaker_loop(self) -> None:
        """Speak queued text (monitor alerts, errors, plugin messages)."""
        while True:
            text = await self._speak_queue.get()
            if not text:
                continue
            try:
                await self._speak_text(text)
            except Exception as e:
                print(f"[Speak] {e}")

    async def _play_audio(self):
        print("[ADHITHIYA] 🔊 Play started")

        # Explicit small output buffer + low-latency hint: a forced large block
        # or a big default device buffer adds avoidable delay before speech
        # reaches the speakers.
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=self._output_blocksize,
            latency="low",
        )
        stream.start()

        # Jitter cushion: before each turn's first write we hold until a little
        # audio has buffered, so a bursty network can't cause underruns/stutter.
        prebuffer = max(0, int(RECEIVE_SAMPLE_RATE * 2 * self._prebuffer_ms / 1000))
        warm = False   # cushion built for the current turn?

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.05
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                        warm = False   # next turn re-buffers its own cushion
                    continue

                self.set_speaking(True)

                # Batch all immediately-available chunks into one write to reduce
                # thread-pool round-trips. Cap at ~100 ms: big enough to cut
                # scheduling overhead, small enough to keep interrupt snappy.
                batch = bytearray(chunk)
                while len(batch) < MAX_BATCH_BYTES:
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # Build the jitter cushion on the first audio of each turn.
                if not warm and prebuffer and len(batch) < prebuffer:
                    loop = asyncio.get_running_loop()
                    deadline = loop.time() + min(self._prebuffer_ms / 1000, 0.25)
                    while len(batch) < prebuffer and loop.time() < deadline:
                        try:
                            nxt = await asyncio.wait_for(
                                self.audio_in_queue.get(), timeout=0.02
                            )
                            batch.extend(nxt)
                        except asyncio.TimeoutError:
                            pass
                    warm = True

                try:
                    await asyncio.get_event_loop().run_in_executor(
                        self._audio_executor, stream.write, bytes(batch)
                    )
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[ADHITHIYA] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """Two-phase briefing: instant greeting first, then news once fetched."""
        memory   = load_memory()
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        lang = _val("language")
        name = _val("name")
        time_str = datetime.now().strftime("%H:%M")

        # Start fetching news immediately — runs in parallel while phase 1 plays
        loop = asyncio.get_event_loop()
        news_future = loop.run_in_executor(None, _fetch_news_sync, "top world news today")

        await asyncio.sleep(0.3)

        # ── Phase 1: instant greeting ─────────────────────────────────────────
        lang_clause = f" Respond in {lang}." if lang else ""
        name_clause = f" Address the user as {name}." if name else ""

        # Inject last session context if available — pop removes it so it's never repeated
        last = await asyncio.to_thread(pop_last_session)
        session_clause = ""
        if last:
            try:
                _delta = (datetime.now() - datetime.strptime(last["date"], "%Y-%m-%d")).days
                _when  = "earlier today" if _delta == 0 else ("yesterday" if _delta == 1 else f"{_delta} days ago")
            except Exception:
                _when = "last time"
            session_clause = (
                f" Also briefly and naturally mention that {_when}: {last['summary']}"
            )

        p1 = (
            f"Greet the user warmly, mention it is {time_str}, and say you are fetching today's news now.{session_clause} "
            f"Keep it to 2 short sentences max. Do not call any tools.{lang_clause}{name_clause}"
        )
        greeting = await self._chat_turn(p1, log_as_user=False)
        if greeting:
            await self._speak_text(greeting)
        self.ui.write_log("SYS: Briefing phase 1 (greeting) sent.")

        # ── Phase 2: deliver news once it's fetched ───────────────────────────
        async def _deliver_news():
            try:
                try:
                    news_text = await asyncio.wait_for(asyncio.wrap_future(news_future), timeout=8.0)
                except Exception as e:
                    self.ui.write_log(f"SYS: News fetch timed out/failed: {e!r}")
                    news_text = ""

                failed = (not news_text) or news_text.startswith(
                    ("No news found", "Search failed", "Please provide")
                )
                if not failed:
                    self.ui.show_content("NEWS — top world news today", news_text)
                    p2 = (
                        f"[BRIEFING] Here are today's top news headlines:\n{news_text}\n\n"
                        "Pick ONE headline, summarise it in one sentence, then say the full list "
                        f"is displayed on screen. Do not call any tools.{lang_clause}"
                    )
                else:
                    self.ui.write_log(
                        f"SYS: News unavailable — backend returned: {news_text[:120]!r}"
                    )
                    p2 = "News headlines could not be fetched right now. Let the user know briefly."

                answer = await self._chat_turn(p2, log_as_user=False)
                if answer:
                    await self._speak_text(answer)
                self.ui.write_log("SYS: Briefing phase 2 (news) sent.")
            except Exception as e:
                print(f"[Briefing] Phase 2 error: {e}")
                self.ui.write_log(f"SYS: Briefing phase 2 failed: {e}")

        asyncio.create_task(_deliver_news())

    # ── Session memory ──────────────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session in 1-2 sentences and save to long_term.json."""
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []    # reset immediately so the next session starts clean

        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip()
        lang = lang or "English"

        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Summarize this conversation in 1-2 sentences in {lang}. "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text, nothing else:\n\n" + convo
        )
        try:
            from core.llm import chat
            resp = await asyncio.to_thread(
                chat, [{"role": "user", "content": prompt}]
            )
            summary = (resp.get("text") or "").strip()
            if summary:
                save_session_summary(summary, lang)
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert:
                continue
            # Don't interrupt an active conversation
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            self.speak(alert)

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            # Don't interrupt if user spoke recently or ADHITHIYA is mid-sentence
            with self._speaking_lock:
                speaking = self._is_speaking
            recent_speech = (time.monotonic() - self._last_user_speech) < 30
            if not speaking and not recent_speech:
                try:
                    alerts = await asyncio.to_thread(monitor_check_all)
                    for alert in alerts:
                        self.speak(alert)
                        self.ui.write_log("SYS: Monitor alert sent.")
                        await asyncio.sleep(6)   # gap between consecutive alerts
                except Exception as e:
                    print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to the LLM so it can decide what (if anything)
        to say proactively. No hardcoded rules — the model makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory       = await asyncio.to_thread(load_memory)
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = self._session_log[-8:] if self._session_log else []
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors or None,
                    recent_turns = recent_turns or None,
                )
                answer = await self._chat_turn(prompt)
                if answer:
                    await self._speak_text(answer)
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Transcribe phone mic PCM chunks (16 kHz mono int16) and queue the
        finished utterance for the conversation loop."""
        q = self._dashboard._phone_audio_queue
        buf = bytearray()
        in_speech = False
        last_speech = time.monotonic()

        def _rms(b: bytes) -> float:
            if not b:
                return 0.0
            try:
                import numpy as np
                arr = np.frombuffer(b, dtype=np.int16).astype(np.float32)
                return float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
            except Exception:
                return 0.0

        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=0.8)
            except asyncio.TimeoutError:
                if in_speech and buf:
                    self._phone_finalize(bytes(buf))
                buf = bytearray()
                in_speech = False
                self._phone_active = False
                continue
            self._phone_active = True
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or self.ui.muted:
                buf = bytearray()
                in_speech = False
                continue
            data = chunk.get("data") if isinstance(chunk, dict) else chunk
            if not isinstance(data, (bytes, bytearray, memoryview)):
                continue
            data = bytes(data)
            if _rms(data) > 300.0:
                if not in_speech:
                    buf = bytearray()
                    in_speech = True
                buf.extend(data)
                last_speech = time.monotonic()
            elif in_speech:
                buf.extend(data)
                if time.monotonic() - last_speech > 0.8:
                    self._phone_finalize(bytes(buf))
                    buf = bytearray()
                    in_speech = False

    def _phone_finalize(self, pcm: bytes) -> None:
        if len(pcm) < SEND_SAMPLE_RATE:
            return
        loop = self._loop
        async def _do():
            try:
                from core.llm import transcribe_wav
                text = (await asyncio.to_thread(transcribe_wav, self._pcm_to_wav(pcm, SEND_SAMPLE_RATE)) or "").strip()
            except Exception:
                text = ""
            if text:
                self._last_user_speech = time.monotonic()
                try:
                    self._transcript_queue.put_nowait(text)
                except asyncio.QueueFull:
                    pass
        try:
            asyncio.run_coroutine_threadsafe(_do(), loop)
        except Exception:
            pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                self.ui.write_log(f"[Web]: {text}")
                try:
                    answer = await self._chat_turn(text)
                    if answer:
                        await self._speak_text(answer)
                except Exception as e:
                    print(f"[Dashboard] Command error: {e}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self._speak_queue = asyncio.Queue(maxsize=200)
        self._transcript_queue = asyncio.Queue(maxsize=20)
        self.audio_in_queue = asyncio.Queue(maxsize=AUDIO_INPUT_QUEUE_LIMIT)
        self._turn_done_event = asyncio.Event()
        self._chat_history = []
        self._briefing_sent = getattr(self, "_briefing_sent", False)

        # Reset transient state
        self._pending_vision = None
        self._vision_cam_active = False
        self._vision_close_pending = False
        self._vision_busy = False
        self._vision_last_time = 0.0
        self._interrupted = False

        # Start dashboard (optional — needs fastapi/uvicorn/cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_connect_callback(self._on_phone_connected)
            asyncio.create_task(self._dashboard.serve())
            asyncio.create_task(self._process_dashboard_commands())
            asyncio.create_task(self._relay_phone_audio())
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None

        voice_status = self._voice_gate.status()
        if voice_status["enabled"]:
            if voice_status["setup_message"]:
                self.ui.write_log(f"VOICE: {voice_status['setup_message']}")
            else:
                self.ui.write_log(
                    f"VOICE: lock enabled; say {voice_status['wake_word']} "
                    "to begin local speaker verification."
                )

        # Background tasks — run for the whole process lifetime
        asyncio.create_task(self._play_audio())
        asyncio.create_task(self._speaker_loop())
        asyncio.create_task(self._run_system_monitor())
        asyncio.create_task(self._run_background_monitor())
        asyncio.create_task(self._run_proactive_mode())

        # Morning briefing — fires once per process launch
        if not self._briefing_sent and get_brief_enabled():
            self._briefing_sent = True
            asyncio.create_task(self._send_startup_briefing())

        # Mic capture thread
        self._mic_thread = threading.Thread(target=self._mic_loop, daemon=True, name="mic")
        self._mic_thread.start()

        print("[ADHITHIYA] Online.")
        self.ui.set_state("LISTENING")
        self.ui.write_log("SYS: ADHITHIYA online.")
        if self._dashboard:
            await self._dashboard.broadcast({"type": "status", "state": "active"})

        # Main conversation loop — one turn at a time
        while True:
            user_text = await self._transcript_queue.get()
            self.ui.set_state("THINKING")
            try:
                answer = await self._chat_turn(user_text)
            except Exception as e:
                print(f"[ADHITHIYA] Turn error: {e}")
                self.ui.write_log(f"ERR: {e}")
                answer = ("Sorry — I hit a problem reaching the AI brain. "
                          "Check your connection and try again.")
            if answer:
                await self._speak_text(answer)
            if not self.ui.muted:
                self.ui.set_state("LISTENING")

def main():
    # face.png sits next to the source in dev and inside the bundle when frozen
    face_path = BASE_DIR / "face.png"
    ui = AdhithiyaUI(str(face_path))

    def runner():
        ui.wait_for_api_key()
        assistant = AdhithiyaAssistant(ui)
        try:
            asyncio.run(assistant.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()