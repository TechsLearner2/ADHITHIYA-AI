#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  ADHITHIYA — quick launcher (run from source, no packaging)
#
#  Double-click this file to run ADHITHIYA. The first run installs everything
#  automatically (a one-time ~1–2 GB download). Use this if you don't want to
#  build a standalone .app — or use build_app.command to make a real app.
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 not found — install Python 3.11/3.12 from python.org first."
  read -r -p "Press Enter to close…" _ || true
  exit 1
fi

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
echo "→ Python $PYVER"
case "$PYVER" in
  3.11|3.12) ;;
  *) echo "⚠  Note: Python 3.11–3.12 is recommended on this OS." ;;
esac

# Create the virtual environment on first run
if [ ! -d ".venv" ]; then
  echo "→ First run: creating environment…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# Install dependencies if they're not there yet
if ! python -c "import openai, PyQt6, sounddevice" >/dev/null 2>&1; then
  echo "→ Installing dependencies (one time)…"
  python -m pip install -q --upgrade pip
  python -m pip install -q -r "$REQ_FILE"
fi

echo "→ Starting ADHITHIYA…"
python main.py
