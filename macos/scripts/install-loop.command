#!/usr/bin/env bash
# ============================================================
#  Double-click to install the GlobalBackground 24-hour loop.
#  Same as running: bash macos/scripts/install-loop.sh
# ============================================================

# cd to the project root so relative paths work when double-clicked from Finder
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

bash "$SCRIPT_DIR/install-loop.sh"

echo ""
echo "Press any key to close this window..."
read -r -n 1
