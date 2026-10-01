#!/usr/bin/env bash
# Double-click launcher for macOS (also works on Linux: ./start_namestack.command).
# First run creates a private Python environment (.venv) and installs everything.
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo "First run: setting things up (takes about a minute)..."
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Python 3 was not found. Install it from https://www.python.org/downloads/ and run this again."
        read -r -p "Press Enter to close."
        exit 1
    fi
    python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip >/dev/null \
        && .venv/bin/python -m pip install -e ".[ai]" || {
        echo "Setup failed. See the error above."
        rm -rf .venv
        read -r -p "Press Enter to close."
        exit 1
    }
fi

echo "Starting namestack... your browser will open at http://127.0.0.1:8787"
echo "Keep this window open while you use it. Close it to stop namestack."
.venv/bin/python -m namestack.server "$@"
