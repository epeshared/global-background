#!/usr/bin/env bash
# ============================================================
#  global-background macOS one-click installer
#
#  This script will:
#    1. Find Python 3.11+
#    2. Auto-install Pillow (if missing)
#    3. Detect screen resolution
#    4. Update config.toml with detected resolution
#    5. Install a launchd agent (runs every 60 minutes)
#    6. Run once immediately
#
#  Usage:
#    bash macos/scripts/install.sh
#    # or double-click macos/scripts/install.command
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

CONFIG_EXAMPLE="$PROJECT_DIR/config.example.toml"
CONFIG_PATH="$PROJECT_DIR/config.toml"
PLIST_TEMPLATE="$SCRIPT_DIR/../launchd/com.global-background.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.global-background.plist"
LOG_DIR="$PROJECT_DIR/logs"
SRC_DIR="$PROJECT_DIR/src"

INTERVAL_SECONDS=3600  # 60 minutes

echo ""
echo "=== GlobalBackground: macOS One-Click Install ==="
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
        if [ -z "$full_path" ]; then
            continue
        fi
        # Check version >= 3.11
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

echo "🔍 Found Python: $PYTHON_EXE"
echo "   Version: $($PYTHON_EXE --version 2>&1)"

# ---- Step 2: Ensure Pillow is installed ----
ensure_pillow() {
    if "$PYTHON_EXE" -c "import PIL" 2>/dev/null; then
        echo "✅ Pillow already installed"
        return 0
    fi

    echo "📦 Installing Pillow..."

    # Try pip install
    if "$PYTHON_EXE" -m pip install --quiet Pillow 2>/dev/null; then
        if "$PYTHON_EXE" -c "import PIL" 2>/dev/null; then
            echo "✅ Pillow installed successfully"
            return 0
        fi
    fi

    # Try with --user flag
    if "$PYTHON_EXE" -m pip install --quiet --user Pillow 2>/dev/null; then
        if "$PYTHON_EXE" -c "import PIL" 2>/dev/null; then
            echo "✅ Pillow installed successfully (user)"
            return 0
        fi
    fi

    # Try ensurepip first
    echo "   Trying ensurepip..."
    "$PYTHON_EXE" -m ensurepip --upgrade 2>/dev/null || true
    if "$PYTHON_EXE" -m pip install --quiet Pillow 2>/dev/null; then
        if "$PYTHON_EXE" -c "import PIL" 2>/dev/null; then
            echo "✅ Pillow installed successfully (via ensurepip)"
            return 0
        fi
    fi

    echo "⚠️  Could not auto-install Pillow. Full-disk images may not be resized."
    echo "   Run manually: $PYTHON_EXE -m pip install Pillow"
    return 0
}

ensure_pillow

# ---- Step 3: Detect screen resolution ----
detect_resolution() {
    # Method 1: system_profiler (no dependencies)
    local res
    res=$(system_profiler SPDisplaysDataType 2>/dev/null \
        | grep -oE 'Resolution: [0-9]+ x [0-9]+' \
        | head -1 || true)
    if [ -n "$res" ]; then
        local w h
        w=$(echo "$res" | grep -oE '[0-9]+' | head -1)
        h=$(echo "$res" | grep -oE '[0-9]+' | tail -1)
        if [ "$w" -gt 0 ] && [ "$h" -gt 0 ]; then
            echo "$w $h"
            return 0
        fi
    fi

    # Method 2: Python with PyObjC (if available)
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
    if [ -n "$py_res" ]; then
        echo "$py_res"
        return 0
    fi

    echo "1920 1080"
}

SCREEN_RES=$(detect_resolution)
SCREEN_W=$(echo "$SCREEN_RES" | awk '{print $1}')
SCREEN_H=$(echo "$SCREEN_RES" | awk '{print $2}')

echo "🖥️  Screen resolution: ${SCREEN_W}x${SCREEN_H}"

# ---- Step 4: Patch config.toml with screen resolution ----
patch_config_resolution() {
    local config="$1" w="$2" h="$3"
    local in_image=false
    local tmp="${config}.tmp"

    while IFS= read -r line || [ -n "$line" ]; do
        if echo "$line" | grep -qE '^\s*\[image\]'; then
            in_image=true
        elif echo "$line" | grep -qE '^\s*\['; then
            in_image=false
        fi

        if $in_image && echo "$line" | grep -qE '^\s*width\s*='; then
            echo "width = $w"
        elif $in_image && echo "$line" | grep -qE '^\s*height\s*='; then
            echo "height = $h"
        else
            echo "$line"
        fi
    done < "$config" > "$tmp"

    mv "$tmp" "$config"
    echo "📝 Updated config.toml: resolution ${w}x${h}"
}

patch_config_resolution "$CONFIG_PATH" "$SCREEN_W" "$SCREEN_H"

# ---- Step 5: Install launchd agent ----
echo "⏰ Installing launchd agent..."

mkdir -p "$LOG_DIR"
mkdir -p "$(dirname "$PLIST_DEST")"

# Generate plist from template
sed \
    -e "s|__PYTHON_EXE__|$PYTHON_EXE|g" \
    -e "s|__CONFIG_PATH__|$CONFIG_PATH|g" \
    -e "s|__SRC_PATH__|$SRC_DIR|g" \
    -e "s|__WORK_DIR__|$PROJECT_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    -e "s|__INTERVAL__|$INTERVAL_SECONDS|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"

# Unload old agent (if any)
launchctl unload "$PLIST_DEST" 2>/dev/null || true

# Load new agent
launchctl load "$PLIST_DEST"
echo "✅ launchd agent installed: com.global-background"
echo "   Interval: every $((INTERVAL_SECONDS / 60)) minutes"

# ---- Step 6: Run once immediately ----
echo ""
echo "🚀 Running first update..."
echo ""

PYTHONPATH="$SRC_DIR" "$PYTHON_EXE" -m global_background once --config "$CONFIG_PATH" || {
    echo ""
    echo "⚠️  First run had errors. Check logs at: $LOG_DIR/"
    echo "   The scheduled agent will retry every hour."
}

echo ""
echo "=== Installation complete ==="
echo ""
echo "Your wallpaper will auto-update every $((INTERVAL_SECONDS / 60)) minutes."
echo ""
echo "Useful commands:"
echo "  View agent status:  launchctl list | grep global-background"
echo "  Run manually:       bash macos/scripts/run-once.sh"
echo "  Uninstall:          bash macos/scripts/uninstall.sh"
echo "  View logs:          cat $LOG_DIR/global-background.log"
echo ""
