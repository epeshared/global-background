"""Cross-platform screen resolution detection.

Delegates to platform-specific implementations:
  - Windows: ctypes GetSystemMetrics (DPI-aware)
  - macOS: NSScreen (PyObjC) or system_profiler
  - Other: fallback to 1920x1080
"""

from __future__ import annotations

from .platform import get_primary_screen_size  # noqa: F401  — re-exported

__all__ = ["get_primary_screen_size"]
