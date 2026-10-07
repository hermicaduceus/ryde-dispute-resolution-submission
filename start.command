#!/bin/bash
# Ryde demo launcher for macOS: double-click this file in Finder.
# It only checks for Python 3.9 or newer, then hands the window to tools/launch.py.

# Run from the repository folder, wherever this file was opened from.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1 \
  || ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"; then
  echo "Python 3.9 or newer is needed to run the Ryde demo. Install it from https://www.python.org/downloads/ and then open this file again."
  read -r -n 1
  exit 1
fi

# exec, so the Terminal window owns one process and Ctrl+C reaches the server.
exec python3 tools/launch.py
