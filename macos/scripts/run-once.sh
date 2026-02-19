#!/usr/bin/env bash
# ============================================================
#  global-background macOS: run once (without installing agent)
#
#  Usage:
#    bash macos/scripts/run-once.sh
#    bash macos/scripts/run-once.sh --dry-run
#    bash macos/scripts/run-once.sh --config path/to/config.toml
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

CONFIG_PATH="$PROJECT_DIR/config.toml"
DRY_RUN=""

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --config)
            CONFIG_PATH="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

if [ ! -f "$CONFIG_PATH" ]; then
    echo "❌ Config file not found: $CONFIG_PATH"
    echo "   Run: cp config.example.toml config.toml"
    exit 1
fi

# Find Python 3.11+
find_python() {
    for cmd in python3.12 python3.11 python3 python; do
        local full_path
        full_path="$(command -v "$cmd" 2>/dev/null || true)"
        if [ -z "$full_path" ]; then
            continue
        fi
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
    exit 1
fi

# Auto-install Pillow if needed
if ! "$PYTHON_EXE" -c "import PIL" 2>/dev/null; then
    echo "📦 Installing Pillow..."
    "$PYTHON_EXE" -m pip install --quiet Pillow 2>/dev/null || \
    "$PYTHON_EXE" -m pip install --quiet --user Pillow 2>/dev/null || \
    echo "⚠️  Could not install Pillow."
fi

# Run
export PYTHONPATH="$PROJECT_DIR/src"
"$PYTHON_EXE" -m global_background once --config "$CONFIG_PATH" $DRY_RUN
