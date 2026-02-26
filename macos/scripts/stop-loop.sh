#!/usr/bin/env bash
# ============================================================
#  Stop the global-background loop agent (without uninstalling)
#
#  Usage:
#    bash macos/scripts/stop-loop.sh
#    bash macos/scripts/stop-loop.sh --disable   # also prevent autostart
# ============================================================
set -euo pipefail

LABEL="com.global-background-loop"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DISABLE=false

for arg in "$@"; do
    case "$arg" in
        --disable) DISABLE=true ;;
        *) echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

echo ""
echo "=== GlobalBackground Loop: Stop ==="
echo ""

# Stop the running process (launchctl stop sends SIGTERM)
launchctl stop "$LABEL" 2>/dev/null \
    && echo "✅ Stopped $LABEL." \
    || echo "ℹ️  $LABEL was not running."

if $DISABLE; then
    # Unload prevents autostart at next login
    launchctl unload "$PLIST_DEST" 2>/dev/null \
        && echo "✅ Unloaded (will not restart at login)." \
        || echo "ℹ️  Agent was already unloaded."
    echo "   To re-enable: launchctl load $PLIST_DEST"
fi

echo ""
echo "To remove entirely: bash macos/scripts/uninstall-loop.sh"
echo ""
