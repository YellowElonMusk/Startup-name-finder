#!/usr/bin/env bash
# Double-click launcher for macOS (also works on Linux: ./start_namestack.command).
# First run installs Python if needed, creates a private Python environment (.venv)
# and installs everything. Later runs start instantly.
cd "$(dirname "$0")" || exit 1

has_python() {
    # macOS ships a "python3" stub that only offers to install developer tools,
    # so actually run it before trusting it.
    command -v python3 >/dev/null 2>&1 \
        && python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1
}

if [ ! -x ".venv/bin/python" ]; then
    echo "First run: setting things up (takes a minute or two)..."
    if ! has_python && [ "$(uname)" = "Darwin" ]; then
        echo "Python was not found. Downloading the official installer from python.org..."
        pkg="/tmp/python-3.12.10-macos11.pkg"
        curl -L --fail -o "$pkg" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg" && open -W "$pkg"
        export PATH="/Library/Frameworks/Python.framework/Versions/3.12/bin:$PATH"
    fi
    if ! has_python; then
        echo "Python 3 was not found. Install it from https://www.python.org/downloads/ and run this again."
        read -r -p "Press Enter to close."
        exit 1
    fi
    # Recent pip trusts the system certificate store (needed behind antivirus /
    # company proxies that re-sign HTTPS), so upgrade the bundled one first.
    # An unreachable index still exits 0, so truststore goes first (Python 3.9 lacks it).
    python3 -m venv .venv && { .venv/bin/python -m pip install --use-feature=truststore --upgrade pip >/dev/null 2>&1 \
        || .venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1; } \
        && .venv/bin/python -m pip install -e ".[ai]" || {
        echo "Setup failed. See the error above."
        rm -rf .venv
        read -r -p "Press Enter to close."
        exit 1
    }
fi

echo "Starting SayMyName... your browser will open at http://127.0.0.1:8787"
echo "Keep this window open while you use it. Close it to stop SayMyName."
.venv/bin/python -m namestack.server "$@"
