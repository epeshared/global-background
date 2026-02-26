#!/usr/bin/env bash
# ============================================================
#  global-background macOS — 24-hour animated wallpaper loop
#  installer
#
#  This script will:
#    1. Copy config.example.toml → config.toml (if missing)
#    2. Find Python 3.11+
#    3. Auto-install Pillow (if missing)
#    4. Detect screen resolution → patch config.toml
#    5. Install a launchd agent (com.global-background-loop)
#       that runs the 'loop' command at login and keeps it alive
#    6. Start the loop immediately
#
#  Usage:
#    bash macos/scripts/install-loop.sh
#    # or double-click  macos/scripts/install-loop.command
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

CONFIG_EXAMPLE="$PROJECT_DIR/config.example.toml"
CONFIG_PATH="$PROJECT_DIR/config.toml"
PLIST_TEMPLATE="$SCRIPT_DIR/../launchd/com.global-background-loop.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.global-background-loop.plist"
LABEL="com.global-background-loop"
LOG_DIR="$PROJECT_DIR/logs"
SRC_DIR="$PROJECT_DIR/src"

echo ""
echo "=== GlobalBackground: 24-hour Animated Wallpaper Installer ==="
echo ""

# ---- Step 0: Ensure config.toml exists ----
if [ ! -f "$CONFIG_PATH" ]; then
    if [ -f "$CONFIG_EXAMPLE" ]; then
        echo "📋 Copying config.example.toml → config.toml"
        cp "$CONFIG_EXAMPLE" "$CONFIG_PATH"
    else
        echo "❌ No config.toml or config.example.toml found."
        exit 1
    fi
fi

# ---- Step 1: Find Python 3.11+ ----
find_python() {
    for cmd in python3.12 python3.11 python3 python; do
        local full_path
        full_path="$(command -v "$cmd" 2>/dev/null || true)"
        [ -z "$full_path" ] && continue
        local ver
        ver=$("$full_path" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        local major minor
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            echo "$full_path"
            return 0
        fi
    done
    return 1
}

PYTHON_EXE=""
PYTHON_EXE=$(find_python) || true
if [ -z "$PYTHON_EXE" ]; then
    echo "❌ Python 3.11+ not found."
    echo "   Install from: https://www.python.org/downloads/"
    echo "   Or via Homebrew: brew install python@3.12"
    exit 1
fi
echo "🔍 Found Python: $PYTHON_EXE  ($($PYTHON_EXE --version 2>&1))"

# ---- Step 2: Ensure Pillow is installed ----
if "$PYTHON_EXE" -c "import PIL" 2>/dev/null; then
    echo "✅ Pillow already installed"
else
    echo "📦 Installing Pillow..."
    "$PYTHON_EXE" -m pip install --quiet Pillow 2>/dev/null \
    || "$PYTHON_EXE" -m pip install --quiet --user Pillow 2>/dev/null \
    || { echo "⚠️  Could not install Pillow. Run: $PYTHON_EXE -m pip install Pillow"; }
    "$PYTHON_EXE" -c "import PIL" 2>/dev/null && echo "✅ Pillow installed" || true
fi

# ---- Step 3: Detect screen resolution ----
detect_resolution() {
    local res
    res=$(system_profiler SPDisplaysDataType 2>/dev/null \
        | grep -oE 'Resolution: [0-9]+ x [0-9]+' \
        | head -1 || true)
    if [ -n "$res" ]; then
        local w h
        w=$(echo "$res" | grep -oE '[0-9]+' | head -1)
        h=$(echo "$res" | grep -oE '[0-9]+' | tail -1)
        [ "$w" -gt 0 ] && [ "$h" -gt 0 ] && echo "$w $h" && return 0
    fi
    # Fallback: PyObjC
    local py_res
    py_res=$("$PYTHON_EXE" -c "
try:
    from AppKit import NSScreen
    s = NSScreen.mainScreen()
    f = s.frame()
    sc = s.backingScaleFactor()
    print(int(f.size.width * sc), int(f.size.height * sc))
except:
    pass
" 2>/dev/null || true)
    [ -n "$py_res" ] && echo "$py_res" && return 0
    echo "1920 1080"
}

SCREEN_RES=$(detect_resolution)
SCREEN_W=$(echo "$SCREEN_RES" | awk '{print $1}')
SCREEN_H=$(echo "$SCREEN_RES" | awk '{print $2}')
echo "🖥️  Screen: ${SCREEN_W}x${SCREEN_H}"

# ---- Step 4: Patch config.toml with screen resolution ----
patch_config_resolution() {
    local config="$1" w="$2" h="$3"
    local in_image=false
    local tmp="${config}.tmp"
    while IFS= read -r line || [ -n "$line" ]; do
        if echo "$line" | grep -qE '^\s*\[image\]'; then         in_image=true
        elif echo "$line" | grep -qE '^\s*\['; then              in_image=false; fi
        if   $in_image && echo "$line" | grep -qE '^\s*width\s*=';  then echo "width = $w"
        elif $in_image && echo "$line" | grep -qE '^\s*height\s*='; then echo "height = $h"
        else echo "$line"; fi
    done < "$config" > "$tmp"
    mv "$tmp" "$config"
    echo "📝 Updated config.toml → ${w}x${h}"
}
patch_config_resolution "$CONFIG_PATH" "$SCREEN_W" "$SCREEN_H"

# ---- Step 5: Install launchd agent ----
echo "⚙️  Installing launchd agent: $LABEL ..."
mkdir -p "$LOG_DIR" "$(dirname "$PLIST_DEST")"

# Stop and unload any existing instance
launchctl unload "$PLIST_DEST" 2>/dev/null || true

# Render plist from template
sed \
    -e "s|__PYTHON_EXE__|$PYTHON_EXE|g" \
    -e "s|__CONFIG_PATH__|$CONFIG_PATH|g" \
    -e "s|__SRC_PATH__|$SRC_DIR|g" \
    -e "s|__WORK_DIR__|$PROJECT_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"

# Load the agent (RunAtLoad starts it immediately)
launchctl load "$PLIST_DEST"
echo "✅ launchd agent installed and started (will restart at every login)"

echo ""
echo "=== Installation complete ==="
echo ""
echo "  The loop will backfill up to 24 hourly satellite images, then"
echo "  cycle through them as a wallpaper slideshow."
echo ""
echo "  Log file  :  $LOG_DIR/loop.log"
echo "  Ring buffer: $PROJECT_DIR/out/hourly/h00.jpg … h23.jpg"
echo ""
echo "Useful commands:"
echo "  View status:   launchctl list | grep global-background-loop"
echo "  Tail log:      tail -f $LOG_DIR/loop.log"
echo "  Stop loop:     bash macos/scripts/stop-loop.sh"
echo "  Uninstall:     bash macos/scripts/uninstall-loop.sh"
echo ""
