#!/usr/bin/env bash
set -euo pipefail

LABEL="com.claudetokencounter.menubar"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
rm -f "$PLIST_PATH"

echo "Uninstalled. Your token totals in state.json are untouched -- delete that file too if you want a clean slate."
