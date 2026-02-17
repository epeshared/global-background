from __future__ import annotations

import sys


def get_primary_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary display in physical pixels.

    Best-effort on Windows: tries to make the process DPI-aware so the returned
    size is not scaled (common on 125%/150% display scaling).
    """

    if not sys.platform.startswith("win"):
        # Conservative fallback.
        return (1920, 1080)

    try:
        import ctypes

        user32 = ctypes.windll.user32

        # Try to become DPI-aware to get real pixel dimensions.
        try:
            # Windows 10+: SetProcessDpiAwarenessContext
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass

        SM_CXSCREEN = 0
        SM_CYSCREEN = 1
        w = int(user32.GetSystemMetrics(SM_CXSCREEN))
        h = int(user32.GetSystemMetrics(SM_CYSCREEN))
        if w > 0 and h > 0:
            return (w, h)
    except Exception:
        pass

    return (1920, 1080)
