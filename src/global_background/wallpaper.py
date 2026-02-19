"""Cross-platform wallpaper setter.

Delegates to platform-specific implementations:
  - Windows: ctypes SystemParametersInfoW + winreg
  - macOS: NSWorkspace (PyObjC) or osascript (AppleScript)
"""

from __future__ import annotations

from pathlib import Path

from .platform import set_wallpaper  # noqa: F401  — re-exported

__all__ = ["set_wallpaper"]
