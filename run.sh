#!/usr/bin/env bash
# One-command launcher for the meeting room.
#   ./run.sh              start the room
#   ./run.sh --demo       start with key-free demo agents
#   ./run.sh keys         any other meetingroom command works too
# First run creates a private environment in .venv (nothing is installed
# into your system or conda Python). Later runs start immediately.
set -euo pipefail
cd "$(dirname "$0")"
VENV=".venv"

pick_python() {
  for p in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      echo "$p"; return 0
    fi
  done
  return 1
}

if [ ! -x "$VENV/bin/python" ]; then
  PY="$(pick_python)" || { echo "Python 3.11 or newer is required (e.g. 'brew install python' or conda)."; exit 1; }
  "$PY" -m meetingroom.graphics
  echo "First run: creating $VENV with $("$PY" --version) ..."
  "$PY" -m venv "$VENV"
fi

if [ ! -f "$VENV/.installed" ] || [ requirements.txt -nt "$VENV/.installed" ]; then
  echo "Installing dependencies into $VENV (one time) ..."
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -r requirements.txt
  touch "$VENV/.installed"
fi

if [ $# -eq 0 ]; then set -- run; fi
case "$1" in -*) set -- run "$@";; esac
exec "$VENV/bin/python" -m meetingroom "$@"
