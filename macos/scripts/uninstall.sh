#!/usr/bin/env bash
# ============================================================
#  global-background macOS uninstaller
#
#  Removes the launchd agent. Does NOT delete config or images.
# ============================================================
set -euo pipefail

PLIST_DEST="$HOME/Library/LaunchAgents/com.global-background.plist"

echo ""
echo "=== GlobalBackground: Uninstall ==="
echo ""

if [ -f "$PLIST_DEST" ]; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    echo "✅ Removed launchd agent: com.global-background"
else
    echo "ℹ️  No launchd agent found (already uninstalled?)."
fi

echo ""
echo "Note: Your config.toml, images (out/), and logs are preserved."
echo "      Delete the project folder manually if you want a full cleanup."
echo ""
