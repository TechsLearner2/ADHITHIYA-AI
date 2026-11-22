# PyInstaller spec for a single-file Windows executable.
# Build on Windows with: build_windows.bat

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path.cwd()

# Runtime assets read from disk by the app and its plugin loader.
datas = [
    (str(ROOT / "face.png"), "."),
    (str(ROOT / "core" / "prompt.txt"), "core"),
    (str(ROOT / "config" / "adhithiya.ico"), "config"),
    (str(ROOT / "plugins"), "plugins"),
    (str(ROOT / "dashboard" / "static"), "dashboard/static"),
]

binaries = []
hiddenimports = [
    "openai",
    "cv2",
    "mss",
    "pyautogui",
    "pyperclip",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFilter",
    "qrcode",
    # Windows-only integrations are imported inside feature functions.
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "comtypes.client",
    "pycaw.pycaw",
    "win10toast",
    "pywinauto",
    # Faster-whisper is installed by build_windows.bat for offline hearing.
    "faster_whisper",
    "ctranslate2",
    "av",
]

# Packages with dynamic imports / native runtime libraries. Keep the optional
# Windows-only and offline-STT packages in the build when they are installed.
for package in (
    "sounddevice",
    "cryptography",
    "uvicorn",
    "qrcode",
    "httpx",
    "websockets",
    "playwright",
    "comtypes",
    "pycaw",
    "win10toast",
    "pywinauto",
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "huggingface_hub",
):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hiddenimports
    except Exception as exc:  # noqa: BLE001 — optional modules vary by Python build
        print(f"[spec] collect_all({package!r}) skipped: {exc}")

# openai uses lazy imports; collect its submodules so the client loads in a
# frozen executable as well as it does from source.
try:
    hiddenimports += collect_submodules("openai")
except Exception as exc:  # noqa: BLE001
    print(f"[spec] collect_submodules('openai') skipped: {exc}")

analysis = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "setuptools", "pip", "pytest"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="ADHITHIYA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "config" / "adhithiya.ico"),
)
