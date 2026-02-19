#!/usr/bin/env bash
# ============================================================
#  global-background macOS one-click installer
#  Double-click this file to install. (macOS will open Terminal)
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SCRIPT_DIR/install.sh"
