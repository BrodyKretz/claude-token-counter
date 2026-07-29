#!/usr/bin/env bash
set -euo pipefail

LABEL="com.claudetokencounter.menubar"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
PYTHON_BIN="$(command -v python3)"

if [ -z "$PYTHON_BIN" ]; then
    echo "python3 not found on PATH. Install Python 3 first." >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c "import rumps" 2>/dev/null; then
    echo "Installing the 'rumps' dependency with $PYTHON_BIN -m pip..."
    "$PYTHON_BIN" -m pip install rumps
fi

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${SCRIPT_DIR}/app.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/agent.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/agent.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "Installed and started. Look for the coin icon (🪙) in your menu bar."
echo "It will also start automatically the next time you log in."
