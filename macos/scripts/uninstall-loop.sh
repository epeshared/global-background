#!/usr/bin/env bash
# ============================================================
#  Uninstall the global-background loop agent.
#  Cached images (out/hourly/) and logs are NOT deleted.
#
#  Usage:
#    bash macos/scripts/uninstall-loop.sh
# ============================================================
set -euo pipefail

LABEL="com.global-background-loop"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"

echo ""
echo "=== GlobalBackground Loop: Uninstall ==="
echo ""

if [ -f "$PLIST_DEST" ]; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    echo "✅ Removed launchd agent: $LABEL"
else
    echo "ℹ️  No agent found (already uninstalled?)."
fi

echo ""
echo "Note: config.toml, cached images (out/hourly/) and logs are preserved."
echo "      Delete the project folder manually for a full cleanup."
echo ""
