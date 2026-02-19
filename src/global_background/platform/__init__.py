"""Cross-platform abstraction for OS-specific operations.

Exports:
  - set_wallpaper(image_path, style)
  - get_primary_screen_size() -> (width, height)

Platform-specific implementations live in:
  - platform/windows.py  (Windows: ctypes, winreg)
  - platform/macos.py    (macOS: osascript, AppKit)
"""

from __future__ import annotations

import sys
from pathlib import Path


def set_wallpaper(image_path: Path, style: str = "fill") -> None:
    """Set the desktop wallpaper. Delegates to the current platform's implementation."""
    if sys.platform.startswith("win"):
        from .windows import set_wallpaper as _impl
    elif sys.platform == "darwin":
        from .macos import set_wallpaper as _impl
    else:
        raise RuntimeError(
            f"Wallpaper setting is not supported on {sys.platform}. "
            "Supported platforms: Windows, macOS."
        )
    _impl(image_path, style=style)


def get_primary_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary display in physical pixels."""
    if sys.platform.startswith("win"):
        from .windows import get_primary_screen_size as _impl
    elif sys.platform == "darwin":
        from .macos import get_primary_screen_size as _impl
    else:
        return (1920, 1080)
    return _impl()
