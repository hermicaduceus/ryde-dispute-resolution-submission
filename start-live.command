#!/bin/bash
# Ryde live launcher for macOS: double-click this file in Finder.
# The live helper reads the privately delivered .env.live sidecar.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1 \
  || ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"; then
  echo "Python 3.9 or newer is needed to run the Ryde live demo. Install it from https://www.python.org/downloads/ and then open this file again."
  read -r -n 1
  exit 1
fi

exec python3 tools/launch_live.py "$@"
