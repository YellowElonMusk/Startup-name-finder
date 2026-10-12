#!/usr/bin/env bash
# SayMyName one-line installer for macOS / Linux. Paste this into Terminal:
#
#   curl -fsSL https://raw.githubusercontent.com/YellowElonMusk/Startup-name-finder/main/install.sh | bash
#
# Downloads SayMyName into ~/SayMyName and starts it. Running it again updates the app.
set -euo pipefail

repo="https://github.com/YellowElonMusk/Startup-name-finder/archive/refs/heads/main.tar.gz"
dest="$HOME/SayMyName"

echo "Downloading SayMyName..."
mkdir -p "$dest"
# Extract over any previous install; its .venv is kept so updates start fast.
curl -fsSL "$repo" | tar -xz -C "$dest" --strip-components=1
chmod +x "$dest/start_namestack.command"

echo "Installed in $dest"
echo "Next time, double-click start_namestack.command in that folder."
# Re-attach stdin to the terminal: when piped from curl it is the script itself.
if (exec < /dev/tty) 2>/dev/null; then
    exec bash "$dest/start_namestack.command" < /dev/tty
fi
exec bash "$dest/start_namestack.command" < /dev/null
