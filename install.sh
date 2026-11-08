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

echo "Building Claude Tracker.app..."
APP_EXEC="$("$PYTHON_BIN" "$SCRIPT_DIR/build_app.py" --python "$PYTHON_BIN" | tail -n 1)"
if [ ! -x "$APP_EXEC" ]; then
    echo "Building the app failed." >&2
    exit 1
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
        <string>${APP_EXEC}</string>
        <string>--foreground</string>
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
# bootout returns before the old copy has fully stopped; wait for it, or
# bootstrap fails with "5: Input/output error".
for _ in $(seq 1 50); do
    launchctl print "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || break
    sleep 0.1
done
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

APP_BUNDLE="${APP_EXEC%/Contents/MacOS/*}"
echo "Installed and started. Look for the coin icon (🪙) in your menu bar."
echo "Claude Tracker is also in Finder at: ${APP_BUNDLE}"
echo "It will start automatically the next time you log in."
