#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  ADHITHIYA — quick launcher (run from source, no packaging)
#
#  Double-click this file to run ADHITHIYA. The first run installs everything
#  automatically (a one-time ~1–2 GB download). Use this if you don't want to
#  build a standalone .app — or use build_app.command to make a real app.
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")"

# ── Pick a working Python (3.11–3.13 recommended) ────────────────────────────
PYTHON_BIN=""
for PY in python3.13 python3.12 python3.11 python3; do
  if command -v "$PY" >/dev/null 2>&1 && "$PY" -c "import sys" >/dev/null 2>&1; then
    PYTHON_BIN="$PY"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "❌ No working Python found — install Python 3.11–3.13 from python.org first."
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

PYVER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "→ Python $PYVER ($PYTHON_BIN)"
case "$PYVER" in
  3.11|3.12|3.13) ;;
  *) echo "⚠  Note: Python 3.11–3.13 is recommended on this OS." ;;
esac

# ── Create (or rebuild) the virtual environment ──────────────────────────────
NEED_NEW=0
if [ ! -d ".venv" ]; then
  NEED_NEW=1
elif ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
  echo "→ Old environment is broken (its Python was removed) — rebuilding…"
  rm -rf .venv
  NEED_NEW=1
fi
if [ "$NEED_NEW" = "1" ]; then
  echo "→ First run: creating environment…"
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# ── Install dependencies if they're not there yet ────────────────────────────
if ! python -c "import openai, PyQt6, sounddevice" >/dev/null 2>&1; then
  echo "→ Installing dependencies (one time)…"
  python -m pip install -q --upgrade pip
  python -m pip install -q -r "$REQ_FILE" || {
    echo "⚠  Dependency install had a problem — see the messages above."
    echo "   You can re-run this launcher to try again."
  }
fi

echo "→ Starting ADHITHIYA…"
python main.py
