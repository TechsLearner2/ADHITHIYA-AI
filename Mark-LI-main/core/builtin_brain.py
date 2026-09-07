"""🧠 The built-in brain — a real neural net living on this machine.

This is what makes ADHITHIYA's "brain" independent of any account, API key or
subscription. The first time you pick built-in mode it downloads two things
into ~/.adhithiya/brain/ (one time, then fully offline forever):

  1. the engine  — llama.cpp's ``llama-server`` official prebuilt binary
                   (≈ 11 MB; Apple Silicon / Intel / Windows / Linux),
  2. the model    — a small open-weight instruct GGUF (Qwen2.5, Apache-2.0;
                   default "balanced" ≈ 2 GB; see MODEL_PROFILES below).

Then it runs llama-server on 127.0.0.1 (never exposed to the network) and
ADHITHIYA talks to it through the same OpenAI-compatible door it uses for
Groq/Ollama — so tool calling, memory, plugins and the whole agent loop work
unchanged, with zero cost and zero internet.

    python3 -m core.builtin_brain status                 # what's installed
    python3 -m core.builtin_brain install --profile balanced
    python3 -m core.builtin_brain start / stop

Everything here is standard-library only, so no extra pip packages.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# ── identity ─────────────────────────────────────────────────────────────────
# The model "name" ADHITHIYA always addresses the brain by. It is passed as
# llama-server's --alias, so any GGUF file can sit behind this one name.
BUILTIN_MODEL      = "adhithiya-brain"
BUILTIN_PORT       = 18771          # localhost-only service port
BUILTIN_CTX_SIZE   = 8192           # tokens of context the brain keeps in RAM
BUILTIN_MAX_TOKENS = 1024           # cap on a single reply (tool loops continue)
DEFAULT_PROFILE    = "balanced"

# Engine builds roll out almost daily; pin one known-good build so every
# install is deterministic. Override via config "builtin_engine_version"
# (e.g. bump to the next b-build), or set ADHITHIYA_BRAIN_ENGINE_URL.
ENGINE_VERSION = "b10839"

# ── model profiles ──────────────────────────────────────────────────────────
# All Qwen2.5-Instruct GGUF quants below are Apache-2.0 licensed, produce no
# <think> monologue, and have solid tool/function calling — the right default
# for a CPU/offline brain.  The "strong" file comes from bartowski's re-quant
# (single-file; the official 7B repo ships split in two parts).
MODEL_PROFILES: dict[str, dict] = {
    "tiny": {
        "label": "Qwen2.5 0.5B  (fastest — old Intel Macs)",
        "file":  "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "url":   "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "approx_gb": 0.5,
    },
    "fast": {
        "label": "Qwen2.5 1.5B  (quick, low RAM)",
        "file":  "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "url":   "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "approx_gb": 1.0,
    },
    "balanced": {
        "label": "Qwen2.5 3B  (recommended — speed + brains)",
        "file":  "qwen2.5-3b-instruct-q4_k_m.gguf",
        "url":   "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
        "approx_gb": 2.0,
    },
    "strong": {
        "label": "Qwen2.5 7B  (smartest — needs ~8 GB RAM free)",
        "file":  "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "url":   "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "approx_gb": 4.7,
    },
}

_UA = "ADHITHIYA-BuiltinBrain/1.0 (+offline assistant)"


# ── paths ────────────────────────────────────────────────────────────────────

def brain_dir() -> Path:
    """Where the brain lives: ~/.adhithiya/brain (env-overridable for tests)."""
    env = os.environ.get("ADHITHIYA_BRAIN_DIR")
    if env:
        return Path(env).expanduser()
    from memory.config_manager import get_data_dir
    return get_data_dir() / "brain"


def _engine_dir() -> Path:
    return brain_dir() / "engine"


def _models_dir() -> Path:
    return brain_dir() / "models"


def _registry_path() -> Path:
    return brain_dir() / "registry.json"


def _log_path() -> Path:
    return brain_dir() / "server.log"


# ── config (read straight from the api_keys.json file; no circular imports) ──

def _cfg() -> dict:
    try:
        from memory.config_manager import load_api_keys
        return load_api_keys() or {}
    except Exception:
        return {}


def profile_name() -> str:
    c = _cfg().get("builtin_profile") or DEFAULT_PROFILE
    return str(c).strip().lower() if str(c).strip().lower() in MODEL_PROFILES else DEFAULT_PROFILE


def model_url() -> tuple[str, str]:
    """(download_url, filename) for the configured profile (or custom URL)."""
    custom = str(_cfg().get("builtin_model_url") or "").strip()
    if custom:
        return custom, Path(custom.split("?")[0]).name or "model.gguf"
    p = MODEL_PROFILES[profile_name()]
    return p["url"], p["file"]


def engine_version() -> str:
    v = str(_cfg().get("builtin_engine_version") or "").strip()
    return v if v.startswith("b") and v[1:].isdigit() else ENGINE_VERSION


def server_port() -> int:
    try:
        return int(_cfg().get("builtin_port") or BUILTIN_PORT)
    except (TypeError, ValueError):
        return BUILTIN_PORT


def ctx_size() -> int:
    try:
        return int(_cfg().get("builtin_ctx_size") or BUILTIN_CTX_SIZE)
    except (TypeError, ValueError):
        return BUILTIN_CTX_SIZE


def gpu_layers() -> int:
    try:
        return int(_cfg().get("builtin_gpu_layers") or 0)
    except (TypeError, ValueError):
        return 0


# ── platform asset mapping ───────────────────────────────────────────────────

def platform_asset() -> str:
    """llama.cpp release-asset descriptor for this machine, e.g. 'macos-arm64'.

    Raises RuntimeError on an unsupported combination so callers can show a
    clear message instead of a confusing HTTP 404.
    """
    m = _machine()
    a = _arch()
    if m == "darwin":
        return f"macos-{a}"
    if m == "linux":
        return f"ubuntu-{a}"
    if m == "win32":
        return f"win-cpu-{a}"
    raise RuntimeError(f"Built-in brain: no llama.cpp build for this OS ({m}). "
                       "Use the Groq (free key) or Ollama local mode instead.")


def _machine() -> str:
    return sys.platform  # darwin / linux / win32


def _arch() -> str:
    import platform
    a = platform.machine().lower()
    if a in ("x86_64", "amd64", "intel"):
        return "x64"
    if a in ("arm64", "aarch64"):
        return "arm64"
    raise RuntimeError(f"Built-in brain: unsupported CPU architecture {a!r}.")


def engine_asset_url() -> str:
    """Direct download URL of the llama.cpp engine bundle for this machine."""
    custom = str(os.environ.get("ADHITHIYA_BRAIN_ENGINE_URL") or "").strip()
    if custom:
        return custom
    ver = engine_version()
    tag = f"llama-{ver}-bin-{platform_asset()}"
    ext = ".zip" if sys.platform == "win32" else ".tar.gz"
    return (f"https://github.com/ggml-org/llama.cpp/releases/download/"
            f"{ver}/{tag}{ext}")


def _archive_members(src: Path) -> list:
    if src.name.endswith(".zip"):
        with zipfile.ZipFile(src) as z:
            return z.namelist()
    with tarfile.open(src) as t:
        return t.getnames()


def _extract(src: Path, dest: Path) -> Path:
    """Extract the engine bundle; return the llama-server binary path."""
    dest.mkdir(parents=True, exist_ok=True)
    if src.name.endswith(".zip"):
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                target = (dest / info.filename).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise RuntimeError(f"Unsafe zip path in {src.name}")
                if info.is_dir():
                    continue
                z.extract(info, dest)
    else:
        with tarfile.open(src) as t:
            for member in t.getmembers():
                target = (dest / member.name).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise RuntimeError(f"Unsafe tar path in {src.name}")
                if member.isdir():
                    continue
                if member.issym() or member.islnk():
                    # llama bundles ship *.so.0 / *.dylib as symlinks — the
                    # loader needs them (e.g. libllama-common.so.0).
                    link = member.linkname
                    if os.path.isabs(link):
                        raise RuntimeError(f"Absolute symlink in {src.name}: {link}")
                    rel = os.path.normpath(
                        os.path.join(os.path.dirname(member.name), link))
                    if rel.startswith("..") or rel.startswith("/"):
                        raise RuntimeError(f"Unsafe symlink in {src.name}: {link}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.is_symlink() or target.exists():
                        target.unlink(missing_ok=True)
                    target.symlink_to(link)
                    continue
                if not member.isfile():
                    continue
                t.extract(member, dest)
    # locate the server binary wherever the bundle put it (root, bin/, …)
    exe = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    for p in sorted(dest.rglob(exe), key=lambda p: len(p.parts)):
        p.chmod(p.stat().st_mode | 0o111)
        return p
    raise RuntimeError("llama.cpp bundle extracted but llama-server binary "
                       f"was not found inside {dest}.")


# ── downloads (resumable, stdlib-only) ──────────────────────────────────────

def _download(url: str, dest: Path, progress=None, attempts: int = 4) -> Path:
    """Download to dest (.part-resumed). Calls progress(done, total_bytes|None)
    no more often than ~once a second / every 2% — safe for UI logs.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last_report = {"t": 0.0, "pct": -1}

    def _report(done: int, total: int | None):
        now = time.monotonic()
        pct = (100.0 * done / total) if total else -1.0
        if (now - last_report["t"] >= 1.0 or pct - last_report["pct"] >= 2.0
                or done == total):
            last_report["t"] = now
            last_report["pct"] = pct
            if progress:
                progress(done, total)

    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        if part.exists():
            start = part.stat().st_size
        else:
            start = 0
        headers = {"User-Agent": _UA}
        if start > 0:
            headers["Range"] = f"bytes={start}-"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as r:
                if r.status == 416:            # range not satisfiable → restart
                    part.unlink(missing_ok=True)
                    continue
                total: int | None = None
                cl = r.headers.get("Content-Length")
                cr = r.headers.get("Content-Range")
                if cr and "/" in cr:
                    try:
                        total = int(cr.rsplit("/", 1)[1])
                    except ValueError:
                        total = None
                if total is None and cl:
                    try:
                        total = int(cl) + start
                    except ValueError:
                        total = None
                done = start
                mode = "ab" if start > 0 else "wb"
                with open(part, mode) as fh:
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        _report(done, total)
                if total is not None and done < total:
                    raise RuntimeError(f"short download: {done}/{total}")
            os.replace(part, dest)
            return dest
        except Exception as e:  # noqa: BLE001 — retried below
            last_err = e
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Download failed after {attempts} attempts: "
                       f"{last_err}")


# ── registry ─────────────────────────────────────────────────────────────────

def _read_registry() -> dict:
    try:
        return json.loads(_registry_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_registry(data: dict) -> None:
    _registry_path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _registry_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, _registry_path())


# ── install ──────────────────────────────────────────────────────────────────

_INSTALL_LOCK = threading.Lock()
_INSTALLING = False   # True while a first-time install is in flight


def installing() -> bool:
    return _INSTALLING


def install(profile: str | None = None, progress=None) -> dict:
    """Install (engine + model) if missing. progress(msg:str) for UI logs.

    Safe to call from any thread; concurrent callers block until done.
    """
    global _INSTALLING
    with _INSTALL_LOCK:
        _INSTALLING = True
        try:
            if progress:
                progress("Starting the one-time brain install…")
            engine = install_engine(progress)
            model = install_model(profile, progress)
            result = {"engine": engine, "model": model}
            if progress:
                progress("Brain install complete — ADHITHIYA can think offline.")
            return result
        finally:
            _INSTALLING = False


def install_engine(progress=None) -> str:
    reg = _read_registry()
    want = engine_version()
    if reg.get("engine_version") == want and server_binary() is not None:
        return str(server_binary())
    url = engine_asset_url()
    fname = f"llama-{want}-bin-{platform_asset()}"
    fname += ".zip" if sys.platform == "win32" else ".tar.gz"
    arc = brain_dir() / fname
    if progress:
        progress(f"Downloading the engine ({fname}, ~11–18 MB)…")
    _download(url, arc, progress=None)   # small; no progress spam needed
    if progress:
        progress(f"Engine downloaded — unpacking…")
    exe = _extract(arc, _engine_dir())
    _write_registry({**reg, "engine_version": want, "engine_exe": str(exe)})
    return str(exe)


def install_model(profile: str | None = None, progress=None) -> str:
    url, fname = model_url() if profile is None else _profile_url(profile)
    dest = _models_dir() / fname
    if dest.exists():
        reg = _read_registry()
        if reg.get("model_file") == fname:
            return str(dest)
    profile = profile or profile_name()
    approx = MODEL_PROFILES.get(profile, {}).get("approx_gb")
    label = MODEL_PROFILES.get(profile, {}).get("label", fname)
    if progress:
        size_note = f" (≈ {approx} GB)" if approx else ""
        progress(f"Downloading the brain model: {label}{size_note} — "
                 f"one time only, resumable.")
    _download(url, dest, progress=_scaled_progress(progress))
    reg = _read_registry()
    _write_registry({**reg, "model_file": fname, "model_url": url,
                     "model_profile": profile})
    return str(dest)


def _profile_url(profile: str) -> tuple[str, str]:
    p = profile.strip().lower()
    if p in MODEL_PROFILES:
        return MODEL_PROFILES[p]["url"], MODEL_PROFILES[p]["file"]
    raise RuntimeError(f"Unknown built-in brain profile {profile!r}. Choose: "
                       + ", ".join(MODEL_PROFILES))


def _scaled_progress(progress):
    """Adapt the byte-progress callback into UI log lines (~every 2%)."""
    if not progress:
        return None

    def _cb(done: int, total: int | None):
        if total:
            progress(f"Downloading brain model… {100.0 * done / total:4.0f}% "
                     f"({done / 1e6:.0f} / {total / 1e6:.0f} MB)")
        else:
            progress(f"Downloading brain model… {done / 1e6:.0f} MB")

    return _cb


def server_binary() -> Path | None:
    reg = _read_registry()
    exe = reg.get("engine_exe")
    if exe and Path(exe).exists():
        return Path(exe)
    return None


def model_file() -> Path | None:
    reg = _read_registry()
    f = reg.get("model_file")
    if not f:
        return None
    p = _models_dir() / f
    return p if p.exists() else None


# ── server lifecycle ─────────────────────────────────────────────────────────

_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()
_proc_port: int | None = None


def _base() -> str:
    return f"http://127.0.0.1:{server_port()}"


def health() -> bool:
    body = _http_get(_base() + "/health", timeout=1.5)
    if not body:
        return False
    try:
        return json.loads(body).get("status") == "ok"
    except Exception:
        return "ok" in body


def _http_get(url: str, timeout: float = 3.0, key: str | None = None) -> str | None:
    try:
        headers = {"User-Agent": _UA}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2048).decode("utf-8", "replace").strip()
    except Exception:
        return None


def status() -> dict:
    """Cheap status snapshot — never downloads, never blocks for long."""
    reg = _read_registry()
    mf = model_file()
    alive = health()
    return {
        "engine": bool(server_binary()),
        "engine_version": reg.get("engine_version"),
        "model": mf.name if mf else None,
        "model_profile": reg.get("model_profile"),
        "server": alive,
        "port": server_port(),
        "installing": installing(),
    }


def ensure_server(progress=None) -> int:
    """Make sure llama-server is up and the brain loaded. Raises RuntimeError
    with actionable text when anything is missing. Blocks until /health is ok
    (first cold load can take a minute+ on CPU-only Macs). Returns the port.
    """
    with _proc_lock:
        if _running_ours():
            return server_port()
        exe = server_binary()
        if exe is None:
            raise RuntimeError(
                "The built-in brain isn't installed yet. On the setup screen "
                "choose 'INSTALL BUILT-IN BRAIN' (one-time ≈2 GB download, "
                "then it works fully offline with no key), or run: "
                "python3 -m core.builtin_brain install")
        model = model_file()
        if model is None:
            raise RuntimeError(
                "The built-in brain engine is here but no model file. Install "
                "it with: python3 -m core.builtin_brain install "
                f"(profile {profile_name()})")
        _start(exe, model)
        _wait_healthy(exe)
        return server_port()


def _running_ours() -> bool:
    """Is a server on our port already answering with our model alias?"""
    if not health():
        return False
    try:
        from core import llm  # lazy: llm imports this module at the top
        alias = llm.chat_model()
    except Exception:
        alias = BUILTIN_MODEL
    # /health is auth-exempt but /v1/models is not — send our localhost token.
    models = _http_get(_base() + "/v1/models", timeout=2.0, key="builtin") or ""
    return alias in models


def _start(exe: Path, model: Path) -> None:
    global _proc, _proc_port
    port = server_port()
    try:
        from core import llm
        alias = llm.chat_model()
    except Exception:
        alias = BUILTIN_MODEL
    args = [
        str(exe), "-m", str(model),
        "--host", "127.0.0.1", "--port", str(port),
        "--alias", alias,
        "--ctx-size", str(ctx_size()),
        "--no-ui", "--parallel", "1",
        "--api-key", "builtin",         # matches llm.get_api_key() placeholder
    ]
    ngl = gpu_layers()
    if ngl > 0:
        args += ["--gpu-layers", str(ngl)]
    brain_dir().mkdir(parents=True, exist_ok=True)
    logf = open(_log_path(), "ab")
    kwargs: dict = {"stdout": logf, "stderr": subprocess.STDOUT,
                    "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # llama.cpp bundles its .so/.dylib siblings next to the binary but does not
    # bake an $ORIGIN rpath into every build — make the loader look there
    # (harmless on Windows, where the exe dir is searched by default).
    env = dict(os.environ)
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        env[var] = str(exe.parent) + (os.pathsep + env[var] if env.get(var) else "")
    kwargs["env"] = env
    print(f"[BRAIN] starting llama-server on 127.0.0.1:{port} (model {model.name})")
    _proc = subprocess.Popen(args, **kwargs)
    _proc_port = port


def _wait_healthy(exe: Path, timeout: float = 420.0) -> None:
    """Poll /health until the model answers or the process dies."""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if _proc is not None and _proc.poll() is not None:
            raise RuntimeError(_dead_server_msg(exe))
        if health():
            print(f"[BRAIN] brain online on 127.0.0.1:{server_port()} "
                  f"(loaded in {time.monotonic() - started:.0f}s)")
            return
        time.sleep(1.0)
    raise RuntimeError(_dead_server_msg(exe, timed_out=True))


def _dead_server_msg(exe: Path, timed_out: bool = False) -> str:
    tail = ""
    try:
        lines = _log_path().read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-6:])
    except Exception:
        pass
    how = "still not answering after a long load" if timed_out else "exited"
    return (f"The built-in brain server {how}. Last log:\n{tail or '(empty)'}\n"
            f"Try `python3 -m core.builtin_brain restart`, or delete "
            f"{brain_dir()} and reinstall.")


def stop_server() -> None:
    """Terminate llama-server (idempotent). Registered at exit too."""
    global _proc
    with _proc_lock:
        if _proc is not None and _proc.poll() is None:
            try:
                _proc.terminate()
                _proc.wait(timeout=5)
            except Exception:
                try:
                    _proc.kill()
                except Exception:
                    pass
        _proc = None


def warmup(progress=None) -> bool:
    """Load the model into RAM now so the first question is fast.

    Sends a 1-token request in a background thread; the load itself can take
    a minute on CPU-only Macs — never blocks the caller.
    """
    if not health():
        return False

    def _warm():
        try:
            body = json.dumps({
                "model": BUILTIN_MODEL,
                "messages": [{"role": "user", "content": "Say OK."}],
                "max_tokens": 2,
            }).encode("utf-8")
            req = urllib.request.Request(
                _base() + "/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer builtin",
                         "User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=600.0) as r:
                r.read()
            if progress:
                progress("The brain is warm.")
        except Exception as e:  # noqa: BLE001 — best-effort
            if progress:
                progress(f"Brain warm-up note: {e}")

    threading.Thread(target=_warm, daemon=True, name="builtin-warmup").start()
    return True


# ── standalone CLI (troubleshooting / installs without the UI) ──────────────

def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="python3 -m core.builtin_brain",
                                 description="ADHITHIYA's built-in offline brain")
    ap.add_argument("action", choices=["status", "install", "start",
                                       "stop", "restart"])
    ap.add_argument("--profile", default=None, choices=list(MODEL_PROFILES))
    args = ap.parse_args()
    if args.action == "status":
        for k, v in status().items():
            print(f"{k:14} {v}")
        return
    if args.action == "install":
        print(f"Profile: {args.profile or profile_name()}")
        install(args.profile, progress=lambda m: print("·", m))
        print("Done. Run `python3 -m core.builtin_brain start` to load it.")
        return
    if args.action == "start":
        port = ensure_server()
        print(f"Brain online at http://127.0.0.1:{port} — press Ctrl-C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            stop_server()
        return
    if args.action == "stop":
        stop_server()
        print("Brain stopped.")
        return
    if args.action == "restart":
        stop_server()
        ensure_server()
        print("Brain restarted.")


import atexit
atexit.register(stop_server)


if __name__ == "__main__":
    _cli()
