import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller: bundled data lives in sys._MEIPASS (the app bundle's
        # internal dir), not next to the executable.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent

def get_data_dir() -> Path:
    """User-writable directory for config and state.

    Always ~/.adhithiya — whether run from source (the double-click .command)
    or the frozen .app. Each re-downloaded ZIP is a brand-new folder, so a
    repo-local config would silently wipe the API key, provider choice, memory
    and self-learned procedures on every update. ~/.adhithiya survives all of
    that.
    """
    data_dir = Path.home() / ".adhithiya"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

BASE_DIR    = get_base_dir()
CONFIG_DIR  = get_data_dir() / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"
DEFAULT_ASSISTANT_NAME = "ADHITHIYA"
DEFAULT_WAKE_WORD = "ADHITHIYA"
DEFAULT_SELF_RECOVERY_CONFIG = {
    "enabled": True,
    "max_attempts": 2,
    "timeout": 30,
}

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def _atomic_save(data: dict) -> None:
    """Write the config so a crash can never leave a half-written file, and
    keep it private (0600) — it holds API keys.

    write→chmod→os.replace: the temp file sits in the same directory (same
    filesystem), so the final rename is atomic; readers either see the old
    file or the complete new one, never a truncated mix.
    """
    import os

    ensure_config_dir()
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)          # no-op-ish on Windows; tight elsewhere
    except OSError:
        pass
    os.replace(tmp, CONFIG_FILE)

def _harden_existing_permissions() -> None:
    """Tighten an already-saved config to 0600 (best-effort, one shot per
    session) so keys saved by older builds stop being group/world-readable."""
    import os

    global _PERMS_HARDENED
    if _PERMS_HARDENED:
        return
    _PERMS_HARDENED = True
    try:
        if CONFIG_FILE.exists():
            os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass

_PERMS_HARDENED = False

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(api_key: str, provider: str = "groq") -> None:
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    field = "groq_api_key" if str(provider).strip().lower() == "groq" else "openai_api_key"
    data["provider"] = str(provider).strip().lower()
    data[field] = api_key.strip()

    _atomic_save(data)

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_api_keys() -> dict:
    """Merged view of the user's config.

    Primary source is ~/.adhithiya/config/api_keys.json. A legacy repo-local
    config (older builds wrote there) is also read so a key the user already
    entered is never lost. The most recently modified file wins on conflicts;
    the others only fill gaps (so a stale file can't clobber a newer choice).
    """
    _harden_existing_permissions()
    candidates = [CONFIG_FILE]
    legacy = get_base_dir() / "config" / "api_keys.json"
    try:
        if legacy.exists() and legacy.resolve() != CONFIG_FILE.resolve():
            candidates.append(legacy)
    except Exception:
        pass
    try:
        candidates.sort(key=lambda c: c.stat().st_mtime, reverse=True)
    except Exception:
        pass

    data: dict = {}
    for path in candidates:
        for k, v in _read_json(path).items():
            if k not in data and v not in (None, "", [], {}):
                data[k] = v
    return data

def get_openai_key() -> str | None:
    return load_api_keys().get("openai_api_key")


def get_groq_key() -> str | None:
    return load_api_keys().get("groq_api_key")


def is_configured() -> bool:
    data = load_api_keys()
    key = data.get("groq_api_key") or data.get("openai_api_key")
    return bool(key and len(str(key)) > 15)


def get_assistant_name() -> str:
    """Return the configured assistant name, or ADHITHIYA if not set."""
    return load_api_keys().get("assistant_name", DEFAULT_ASSISTANT_NAME) or DEFAULT_ASSISTANT_NAME


def get_user_name() -> str:
    """Return the configured user name for addressing."""
    return load_api_keys().get("user_name", "")


def get_voice_lock_enabled() -> bool:
    """Return whether the fail-closed local voice gate is enabled."""
    return bool(load_api_keys().get("voice_lock_enabled", False))


def get_wake_word() -> str:
    """Return the configured local wake word."""
    value = load_api_keys().get("wake_word", DEFAULT_WAKE_WORD)
    return str(value or DEFAULT_WAKE_WORD).strip() or DEFAULT_WAKE_WORD


def get_voice_profile_status() -> str:
    """Return dynamic local profile status without importing optional models."""
    try:
        from core.voice_gate import voice_profile_status
        return voice_profile_status(load_api_keys().get("voice_profile_path"))
    except (OSError, ValueError, TypeError):
        return "invalid"


def get_voice_profile_path() -> str:
    """Return the configured local voice profile path."""
    value = load_api_keys().get("voice_profile_path")
    if isinstance(value, str) and value.strip():
        return str(Path(value).expanduser())
    try:
        from core.voice_gate import DEFAULT_PROFILE_PATH
        return str(DEFAULT_PROFILE_PATH)
    except (ImportError, OSError):
        return str(Path.home() / ".adhithiya" / "voice_profile.json")


def get_audio_input_device():
    """Return the configured sounddevice input index/name, if any."""
    value = load_api_keys().get("audio_input_device")
    return value if isinstance(value, (int, str)) and not isinstance(value, bool) else None


def save_audio_input_device(device) -> None:
    """Persist a sounddevice input index or name without touching other config."""
    ensure_config_dir()
    data = load_api_keys()
    if device is None or device == "":
        data.pop("audio_input_device", None)
    else:
        data["audio_input_device"] = device
    _atomic_save(data)


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["assistant_name"] = assistant_name.strip() or DEFAULT_ASSISTANT_NAME
    data["user_name"] = user_name.strip()
    _atomic_save(data)


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


def save_brief_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["morning_brief_enabled"] = enabled
    _atomic_save(data)


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default the moment they're discovered (opt-out model)."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    _atomic_save(data)


def get_agent_mode_enabled() -> bool:
    """Project agent is always available by default (no opt-in "mode").

    Kept as a small helper so an explicit opt-out in config is still honoured,
    but the default is enabled — project work is part of ADHITHIYA's nature.
    """
    data = load_api_keys()
    config = data.get("agent_mode", {}) if isinstance(data, dict) else {}
    if isinstance(config, dict):
        return bool(config.get("enabled", True))
    return bool(data.get("agent_mode_enabled", True)) if isinstance(data, dict) else True


def default_agent_workspace_root() -> Path:
    """A sensible workspace when the user hasn't chosen one: their home folder.

    The safety boundary requires the workspace to contain the app itself, so a
    home-folder default lets the agent work on any of the user's projects while
    still being contained and approval-gated.
    """
    try:
        home = Path.home().expanduser().resolve()
        if home.is_dir():
            return home
    except (OSError, RuntimeError):
        pass
    return BASE_DIR


def get_agent_workspace_root(default: Path | None = None) -> Path:
    """Return a configured workspace boundary, falling back safely to default."""
    try:
        fallback = Path(default or BASE_DIR).expanduser().resolve()
    except (OSError, RuntimeError):
        fallback = BASE_DIR
    data = load_api_keys()
    config = data.get("agent_mode", {}) if isinstance(data, dict) else {}
    configured = config.get("workspace_root") if isinstance(config, dict) else None
    if configured is None and isinstance(data, dict):
        configured = data.get("agent_workspace_root")
    if not isinstance(configured, str) or not configured.strip():
        return fallback
    try:
        candidate = Path(configured).expanduser().resolve()
    except (OSError, RuntimeError):
        return fallback
    # A configured root must contain the application itself. This prevents a
    # typo or an overly broad setting from silently changing the safety boundary.
    try:
        fallback.relative_to(candidate)
    except ValueError:
        return fallback
    return candidate


def get_self_recovery_config() -> dict:
    """Return bounded local recovery settings with safe defaults."""
    data = load_api_keys()
    agent = data.get("agent_mode", {}) if isinstance(data, dict) else {}
    recovery = agent.get("self_recovery", {}) if isinstance(agent, dict) else {}
    if not isinstance(recovery, dict):
        recovery = {}
    try:
        max_attempts = int(recovery.get("max_attempts", DEFAULT_SELF_RECOVERY_CONFIG["max_attempts"]))
    except (TypeError, ValueError):
        max_attempts = 2
    try:
        timeout = int(recovery.get("timeout", DEFAULT_SELF_RECOVERY_CONFIG["timeout"]))
    except (TypeError, ValueError):
        timeout = 30
    return {
        "enabled": bool(recovery.get("enabled", DEFAULT_SELF_RECOVERY_CONFIG["enabled"])),
        "max_attempts": max(1, min(max_attempts, 5)),
        "timeout": max(1, min(timeout, 300)),
    }