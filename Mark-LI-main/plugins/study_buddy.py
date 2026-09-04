"""Study buddy — live class note-taking and study tools for ADHITHIYA.

What it adds on top of the existing ``study_mode`` / NotebookLM plugins:

* ``start_notes``  — record class audio (system sound via a loopback device
  such as BlackHole, or the microphone) in the background, transcribe it with
  the LLM, and keep a running Markdown notes file. Returns immediately; the
  recording keeps running in a background thread for the whole class.
* ``stop_notes``   — finish recording and hand back the notes.
* ``add_note``     — jot down a manual note into the current notes file.
* ``list_notes``   — list saved notes files.
* ``read_notes``   — read back a notes file (latest by default).
* ``summarize``    — turn the notes into a study guide / summary (LLM).
* ``export_notes`` — save a clean copy of the latest notes to the Desktop.

Notes are stored under ``~/.adhithiya/notes/`` (a user-writable location that
survives app updates and frozen .app builds). NotebookLM stays in the user's
own signed-in browser — no passwords are ever requested.
"""

from __future__ import annotations

import io
import json
import queue
import re
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

try:
    from memory.config_manager import get_data_dir, load_api_keys
except Exception:  # pragma: no cover - guard for unusual import contexts
    def get_data_dir() -> Path:
        return Path.home() / ".adhithiya"

    def load_api_keys() -> dict:
        return {}

NOTES_DIR = get_data_dir() / "notes"

_SESSION_LOCK = threading.Lock()
_active: dict | None = None   # the one running recording session

CHUNK_SECONDS = 60            # transcribe in ~1-minute slices
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SAMPLES = 1600          # 0.1 s per callback block
_CHUNK_BYTES = SAMPLE_RATE * 2 * CHUNK_SECONDS

PLUGIN = {
    "name": "study_buddy",
    "description": (
        "Study buddy for ADHITHIYA. Use it to take notes during an online class "
        "(start_notes records and transcribes the class audio in the background, "
        "stop_notes finishes and saves the notes), add manual notes, list/read "
        "notes, summarize notes into a study guide, and export notes to the "
        "Desktop. Use start_notes when the user says 'take notes for me', 'take "
        "notes for this class', 'note this lecture', etc. Prefer this over any "
        "other tool for note-taking."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "start_notes | stop_notes | notes_status | add_note | "
                    "list_notes | read_notes | summarize | export_notes"
                ),
            },
            "topic": {
                "type": "STRING",
                "description": "Subject or class name for the notes (e.g. 'Biology', 'History').",
            },
            "source": {
                "type": "STRING",
                "description": "'system' to capture computer audio (needs a virtual loopback device like BlackHole), or 'mic' for the microphone. Default: system if available, otherwise mic.",
            },
            "device": {
                "type": "STRING",
                "description": "Optional input device index or name to record from.",
            },
            "text": {
                "type": "STRING",
                "description": "Note text for add_note.",
            },
            "file": {
                "type": "STRING",
                "description": "Notes file name for read_notes (omit for the latest).",
            },
            "confirmed": {
                "type": "BOOLEAN",
                "description": "Explicit approval for exporting to the Desktop.",
            },
        },
        "required": ["action"],
    },
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _log(player, message: str) -> None:
    try:
        if player is not None and hasattr(player, "write_log"):
            player.write_log(f"STUDY: {message}")
    except Exception:
        pass


def _api_key() -> str:
    try:
        from core.llm import get_api_key
        return get_api_key()
    except Exception:
        return ""


def _slug(topic: str) -> str:
    topic = re.sub(r"[^A-Za-z0-9]+", "_", str(topic or "class").strip()).strip("_")
    return topic[:40] or "class"


def _latest_file() -> Path | None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(NOTES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _pick_device(parameters: dict) -> object:
    """Choose the input device to record from.

    Priority: explicit ``device`` → ``source`` hint → config ``study_audio_device``
    → first loopback-looking device (BlackHole / Soundflower / virtual) → OS default.
    """
    explicit = parameters.get("device")
    if explicit not in (None, ""):
        return explicit
    source = str(parameters.get("source", "")).strip().lower()
    try:
        cfg = load_api_keys().get("study_audio_device")
    except Exception:
        cfg = None

    try:
        import sounddevice as sd
        devices = sd.query_devices()
    except Exception:
        return explicit or cfg

    if source == "system" or (source == "" and cfg in (None, "")):
        for i, d in enumerate(devices):
            name = str(d.get("name", "")).lower()
            if d.get("max_input_channels", 0) > 0 and any(
                key in name for key in ("blackhole", "loopback", "soundflower", "virtual")
            ):
                return i
    return cfg or None


def _to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _transcribe(pcm: bytes, api_key: str) -> str:
    """Transcribe one audio slice with Whisper. Returns '' on any failure."""
    if not api_key or not pcm:
        return ""
    try:
        from core.llm import transcribe_wav
        return transcribe_wav(_to_wav(pcm))
    except Exception as exc:  # noqa: BLE001 - note-taking must never crash
        print(f"[Study] Transcribe error: {exc}")
        return ""


def _append_note(path: Path, line: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


# ── recording engine ──────────────────────────────────────────────────────────

def _record_loop(sess: dict) -> None:
    """Background thread: capture audio, transcribe in slices, write notes."""
    try:
        import sounddevice as sd

        buf = bytearray()
        q: "queue.Queue[bytes]" = queue.Queue(maxsize=600)

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            try:
                q.put_nowait(bytes(indata))
            except queue.Full:
                pass  # drop rather than grow unbounded on slow transcription

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=BLOCK_SAMPLES,
            device=sess["device"],
            callback=callback,
        ):
            while not sess["stop"].is_set():
                try:
                    buf.extend(q.get(timeout=0.4))
                except queue.Empty:
                    continue
                if len(buf) >= _CHUNK_BYTES:
                    _flush(sess, buf)
            # drain remaining queued blocks, then flush whatever is left
            while True:
                try:
                    buf.extend(q.get_nowait())
                except queue.Empty:
                    break
            if buf:
                _flush(sess, buf)
    except Exception as exc:  # noqa: BLE001
        sess["error"] = str(exc)
        _log(sess.get("player"), f"recording error: {exc}")


def _flush(sess: dict, buf: bytearray) -> None:
    pcm = bytes(buf)
    buf.clear()
    text = _transcribe(pcm, sess["api_key"])
    if not text:
        sess["missed"] = sess.get("missed", 0) + 1
        return
    stamp = datetime.now().strftime("%H:%M")
    _append_note(sess["path"], f"\n## {stamp}\n{text}\n")
    sess["sections"] = sess.get("sections", 0) + 1
    _log(sess.get("player"), f"captured section {sess['sections']}")


# ── plugin entry ──────────────────────────────────────────────────────────────

def _start(parameters: dict, player) -> str:
    global _active
    with _SESSION_LOCK:
        if _active is not None:
            return (
                f"Already taking notes for '{_active['topic']}'. "
                "Say 'stop notes' to finish first."
            )
        api_key = _api_key()
        if not api_key:
            return "No OpenAI API key is configured, so I can't transcribe class audio."

        topic = str(parameters.get("topic") or "Class").strip()
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        path = NOTES_DIR / f"{_slug(topic)}_{datetime.now():%Y%m%d_%H%M%S}.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {topic} — class notes\n")
            f.write(f"Started: {datetime.now():%Y-%m-%d %H:%M}\n")

        sess = {
            "topic": topic,
            "path": path,
            "device": _pick_device(parameters),
            "api_key": api_key,
            "player": player,
            "stop": threading.Event(),
            "sections": 0,
            "missed": 0,
            "error": "",
        }
        sess["thread"] = threading.Thread(
            target=_record_loop, args=(sess,), daemon=True, name="study-buddy"
        )
        _active = sess
        sess["thread"].start()
        _log(player, f"notes started for '{topic}'")

        device_hint = (
            "Recording from the computer's audio (loopback)."
            if str(parameters.get("source", "")).lower() == "system" or _pick_device(parameters) is not None
            else "Recording from the microphone."
        )
        return (
            f"I'm now taking notes for '{topic}'. {device_hint} "
            f"Notes will be saved to {path.name}. "
            "I'll keep transcribing in the background — just tell me 'stop notes' "
            "when the class ends. Tip: press F4 to mute my microphone if I start "
            "reacting to the lecture audio."
        )


def _stop(player) -> str:
    global _active
    with _SESSION_LOCK:
        sess = _active
        _active = None
    if sess is None:
        return "I'm not currently taking notes."
    sess["stop"].set()
    sess["thread"].join(timeout=45)
    _log(player, f"notes stopped for '{sess['topic']}'")
    if sess.get("error"):
        return f"Recording stopped with an error: {sess['error']}"
    lines = sess["path"].read_text(encoding="utf-8").splitlines()
    count = sum(1 for ln in lines if ln.startswith("## "))
    return (
        f"Class notes saved for '{sess['topic']}': {sess['path'].name} "
        f"({count} sections transcribed"
        + (f", {sess.get('missed', 0)} audio slices couldn't be transcribed" if sess.get("missed") else "")
        + "). Say 'summarize my notes' for a study guide, or 'read my notes' to hear them."
    )


def _status() -> str:
    with _SESSION_LOCK:
        sess = _active
    if sess is None:
        return "Not currently recording."
    return (
        f"Recording '{sess['topic']}' — {sess['sections']} sections captured so far, "
        f"saving to {sess['path'].name}."
    )


def _add_note(parameters: dict, player) -> str:
    text = str(parameters.get("text") or "").strip()
    if not text:
        return "Tell me what note to add (text parameter)."
    with _SESSION_LOCK:
        sess = _active
    path = sess["path"] if sess else _latest_file()
    if path is None:
        path = NOTES_DIR / f"notes_{datetime.now():%Y%m%d_%H%M%S}.md"
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text("# Notes\n", encoding="utf-8")
    _append_note(path, f"\n- {datetime.now():%H:%M} — {text}\n")
    _log(player, "manual note added")
    return f"Noted: {text[:200]}"


def _list() -> str:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(NOTES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "No notes yet. Start with 'take notes for my class'."
    out = [f"{len(files)} notes file(s):"]
    for f in files[:10]:
        out.append(f"- {f.name}  ({f.stat().st_size} bytes)")
    return "\n".join(out)


def _read(parameters: dict) -> str:
    name = str(parameters.get("file") or "").strip()
    if name:
        path = NOTES_DIR / Path(name).name
    else:
        path = _latest_file()
    if path is None or not path.exists():
        return "No notes found."
    return path.read_text(encoding="utf-8")[:4000]


def _summarize(parameters: dict, player) -> str:
    name = str(parameters.get("file") or "").strip()
    path = (NOTES_DIR / Path(name).name) if name else _latest_file()
    if path is None or not path.exists():
        return "No notes to summarize yet."
    content = path.read_text(encoding="utf-8")
    api_key = _api_key()
    if not api_key:
        return "No API key configured — I can't summarize."
    try:
        from core.llm import chat
        guide = chat([{"role": "user", "content": (
            "Turn these raw class notes into a clean study guide: key points "
            "as bullet points grouped by topic, then a 3-5 line summary at "
            "the end. Keep all facts from the notes only — do not invent "
            "anything. Notes:\n\n" + content[-12000:]
        )}])["text"]
    except Exception as exc:  # noqa: BLE001
        return f"Could not summarize: {exc}"
    if not guide:
        return "Summarization returned nothing."
    _append_note(path, "\n## Study guide\n" + guide + "\n")
    _log(player, "study guide appended")
    return guide[:4000]


def _export(parameters: dict, player) -> str:
    if not parameters.get("confirmed"):
        return "Confirm exporting these notes to your Desktop with confirmed=true."
    path = _latest_file()
    if path is None or not path.exists():
        return "No notes to export yet."
    try:
        dest = Path.home() / "Desktop" / f"ADHITHIYA_{path.name}"
        dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError as exc:
        return f"Could not export: {exc}"
    _log(player, f"notes exported to Desktop")
    return f"Notes exported to your Desktop: {dest.name}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = str(parameters.get("action", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if action in {"start_notes", "take_notes", "record", "note_this", "start_recording"}:
        return _start(parameters, player)
    if action in {"stop_notes", "stop", "stop_recording", "finish_notes"}:
        return _stop(player)
    if action in {"notes_status", "status"}:
        return _status()
    if action in {"add_note", "note", "remember_note"}:
        return _add_note(parameters, player)
    if action in {"list_notes", "notes", "list"}:
        return _list()
    if action in {"read_notes", "read", "show_notes"}:
        return _read(parameters)
    if action in {"summarize", "summary", "study_guide", "make_notes"}:
        return _summarize(parameters, player)
    if action in {"export_notes", "export"}:
        return _export(parameters, player)
    return (
        "Use study_buddy with one of: start_notes, stop_notes, notes_status, "
        "add_note, list_notes, read_notes, summarize, or export_notes."
    )
