#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  ADHITHIYA — build a standalone macOS app (double-clickable .app bundle)
#
#  What it does:
#    1. Creates a dedicated virtual environment
#    2. Installs all dependencies + PyInstaller
#    3. Builds dist/ADHITHIYA.app
#
#  Just double-click this file in Finder. If macOS asks, allow it to run.
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ADHITHIYA — app builder"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Check for Python ─────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 was not found."
  echo "   Install Python 3.11/3.12 from https://www.python.org/downloads/ first."
  read -r -p "Press Enter to close…" _ || true
  exit 1
fi

echo "→ Python found: $(python3 --version)"

# ── Compatibility: pick packages that match this macOS version ───────────────
REQ_FILE="requirements.txt"
if [ "$(uname -s)" = "Darwin" ]; then
  OS_MAJOR=$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)
  if [ -n "$OS_MAJOR" ] && [ "$OS_MAJOR" -lt 13 ] 2>/dev/null; then
    REQ_FILE="requirements-macos12.txt"
    echo "→ macOS $OS_MAJOR detected — using macOS 12-compatible packages."
  fi
fi

PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
case "$PYVER" in
  3.11|3.12) ;;
  *) echo "⚠  Note: Python 3.11–3.12 is recommended on this OS." ;;
esac

# ── Build environment ────────────────────────────────────────────────────────
if [ ! -d ".venv-build" ]; then
  echo "→ Creating build environment (.venv-build)…"
  python3 -m venv .venv-build
fi
# shellcheck disable=SC1091
source .venv-build/bin/activate

echo "→ Installing dependencies (this is the big step, ~1–2 GB)…"
python -m pip install -q --upgrade pip
python -m pip install -q -r "$REQ_FILE" pyinstaller

echo "→ Installing Playwright browser (for web-browser control)…"
python -m playwright install chromium 2>/dev/null || echo "   ⚠ skipped — browser control will be limited"

# ── Build ────────────────────────────────────────────────────────────────────
echo "→ Building ADHITHIYA.app (this takes a few minutes)…"
python -m PyInstaller ADHITHIYA.spec --noconfirm --clean

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -d "dist/ADHITHIYA.app" ]; then
  echo "✅  SUCCESS!"
  echo ""
  echo "    Your app:  dist/ADHITHIYA.app"
  echo ""
  echo "    → Drag it into /Applications to install."
  echo "    → First launch: right-click → Open (to allow the unsigned app)."
else
  echo "⚠  Build finished, but dist/ADHITHIYA.app was not found."
  echo "   Scroll up to see any error messages."
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
read -r -p "Press Enter to close…" _ || true
