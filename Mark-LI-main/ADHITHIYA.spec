# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for building ADHITHIYA.app on macOS.

Run from the project root (easiest: double-click `build_app.command`, or):
    pyinstaller ADHITHIYA.spec --noconfirm --clean

Output: dist/ADHITHIYA.app  → drag it to /Applications.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

# ── Read-only assets bundled into the app ──────────────────────────────────
datas = [
    ("face.png", "."),
    ("core/prompt.txt", "core"),
    ("config/adhithiya.ico", "config"),
    ("plugins", "plugins"),                      # whole plugin dir (discovered at runtime)
    ("dashboard/static", "dashboard/static"),    # phone-remote web UI
]

binaries = []
hiddenimports = [
    "google.genai",
    "google.genai.types",
    "google.generativeai",
    "cv2",
    "mss",
    "pyautogui",
    "pyperclip",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFilter",
    "qrcode",
]

# Packages with dynamic imports or bundled native libs — collect everything.
for _pkg in (
    "sounddevice",     # PortAudio binary
    "cryptography",    # dashboard encryption
    "uvicorn",         # dashboard server
    "qrcode",
    "httpx",
    "websockets",
):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception as _exc:  # noqa: BLE001 — never fail the build on one package
        print(f"[spec] collect_all('{_pkg}') skipped: {_exc}")

# google-genai uses lazy imports; collect its submodules so the Live API works.
try:
    hiddenimports += collect_submodules("google.genai")
except Exception as _exc:  # noqa: BLE001
    print(f"[spec] collect_submodules('google.genai') skipped: {_exc}")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "setuptools", "pip", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ADHITHIYA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,      # windowed app — no Terminal window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ADHITHIYA",
)
