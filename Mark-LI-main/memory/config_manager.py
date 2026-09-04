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

    In a frozen .app the bundle is read-only, so writable data lives in
    ~/.adhithiya. In a normal source run this is the repo root — behaviour
    is unchanged from before.
    """
    if getattr(sys, "frozen", False):
        data_dir = Path.home() / ".adhithiya"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    return get_base_dir()

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

    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}

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
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


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
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


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
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


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
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


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