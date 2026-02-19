"""macOS-specific platform implementations.

- set_wallpaper: uses NSWorkspace (PyObjC) or osascript fallback
- get_primary_screen_size: uses NSScreen (PyObjC) or system_profiler fallback
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Wallpaper
# ---------------------------------------------------------------------------

# macOS scaling options (used with NSWorkspace if PyObjC is available)
_STYLE_MAP = {
    "fill": 5,      # NSImageScaleProportionallyUpOrDown + crop
    "fit": 3,       # NSImageScaleProportionallyUpOrDown
    "stretch": 1,   # NSImageScaleAxesIndependently
    "center": 0,    # NSImageScaleNone
}


def _set_wallpaper_nsworkspace(path_str: str, style: str) -> bool:
    """Try to set wallpaper using PyObjC (AppKit). Returns True on success."""
    try:
        from AppKit import NSScreen, NSWorkspace  # type: ignore
        from Foundation import NSURL  # type: ignore

        workspace = NSWorkspace.sharedWorkspace()
        url = NSURL.fileURLWithPath_(path_str)

        scaling = _STYLE_MAP.get(style.lower().strip(), 5)
        options = {"NSImageScaling": scaling}

        for screen in NSScreen.screens():
            result, error = workspace.setDesktopImageURL_forScreen_options_error_(
                url, screen, options, None
            )
            if not result:
                return False
        return True
    except ImportError:
        return False
    except Exception:
        return False


def _set_wallpaper_osascript(path_str: str) -> None:
    """Set wallpaper using osascript (AppleScript). Works without PyObjC."""
    # Escape any double-quotes in path
    escaped = path_str.replace('"', '\\"')

    # Strategy 1: System Events (sets all desktops/spaces)
    script_system_events = (
        'tell application "System Events" to '
        f'tell every desktop to set picture to POSIX file "{escaped}"'
    )
    result = subprocess.run(
        ["osascript", "-e", script_system_events],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        return

    # Strategy 2: Finder (older macOS, sets current desktop)
    script_finder = (
        'tell application "Finder" to '
        f'set desktop picture to POSIX file "{escaped}"'
    )
    result = subprocess.run(
        ["osascript", "-e", script_finder],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to set wallpaper via osascript: {result.stderr.strip()}"
        )


def set_wallpaper(image_path: Path, style: str = "fill") -> None:
    """Set the desktop wallpaper on macOS.

    Tries PyObjC (AppKit) first for best control (supports scaling style),
    falls back to osascript (AppleScript) which works without dependencies.
    """
    path = image_path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))

    path_str = str(path)

    # Prefer PyObjC for scaling control
    if _set_wallpaper_nsworkspace(path_str, style):
        return

    # Fallback to osascript (no scaling control, uses current user preference)
    _set_wallpaper_osascript(path_str)


# ---------------------------------------------------------------------------
# Screen resolution
# ---------------------------------------------------------------------------


def _screen_size_nsscreen() -> tuple[int, int] | None:
    """Try to get screen size via PyObjC (AppKit). Returns physical pixels."""
    try:
        from AppKit import NSScreen  # type: ignore

        screen = NSScreen.mainScreen()
        if screen is None:
            return None
        desc = screen.deviceDescription()
        size = desc.get("NSDeviceSize")
        if size is None:
            return None
        scale = screen.backingScaleFactor()
        w = int(size.width * scale)
        h = int(size.height * scale)
        if w > 0 and h > 0:
            return (w, h)
    except ImportError:
        pass
    except Exception:
        pass
    return None


def _screen_size_system_profiler() -> tuple[int, int] | None:
    """Get screen size from system_profiler. Returns physical pixels."""
    try:
        output = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType"],
            timeout=10,
        ).decode("utf-8", errors="replace")

        # Look for "Resolution: 2560 x 1600 Retina" or "Resolution: 3456 x 2234"
        # The first "Resolution:" entry is usually the built-in/primary display.
        matches = re.findall(r"Resolution:\s+(\d+)\s*x\s*(\d+)", output)
        if matches:
            w, h = int(matches[0][0]), int(matches[0][1])
            if w > 0 and h > 0:
                return (w, h)
    except Exception:
        pass
    return None


def _screen_size_screenutil() -> tuple[int, int] | None:
    """Get screen size from macOS screenutil (Quartz display services)."""
    try:
        import Quartz  # type: ignore

        main_id = Quartz.CGMainDisplayID()
        w = Quartz.CGDisplayPixelsWide(main_id)
        h = Quartz.CGDisplayPixelsHigh(main_id)
        if w > 0 and h > 0:
            return (int(w), int(h))
    except ImportError:
        pass
    except Exception:
        pass
    return None


def get_primary_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary display in physical pixels.

    Tries multiple methods:
    1. PyObjC NSScreen (most accurate for Retina)
    2. Quartz CGDisplay (alternative PyObjC path)
    3. system_profiler SPDisplaysDataType (no dependencies)
    4. Fallback: 1920x1080
    """
    for method in (_screen_size_nsscreen, _screen_size_screenutil, _screen_size_system_profiler):
        result = method()
        if result is not None:
            return result

    return (1920, 1080)
