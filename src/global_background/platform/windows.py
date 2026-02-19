"""Windows-specific platform implementations.

- set_wallpaper: uses SystemParametersInfoW + winreg
- get_primary_screen_size: uses GetSystemMetrics (DPI-aware)
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

import winreg

# ---------------------------------------------------------------------------
# Wallpaper
# ---------------------------------------------------------------------------

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02


def _set_reg_wallpaper_style(style: str) -> None:
    style = style.lower().strip()

    if style == "fill":
        wallpaper_style = "10"
        tile = "0"
    elif style == "fit":
        wallpaper_style = "6"
        tile = "0"
    elif style == "stretch":
        wallpaper_style = "2"
        tile = "0"
    elif style == "center":
        wallpaper_style = "0"
        tile = "0"
    elif style == "span":
        wallpaper_style = "22"
        tile = "0"
    else:
        wallpaper_style = "10"
        tile = "0"

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Control Panel\Desktop",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, wallpaper_style)
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, tile)


def set_wallpaper(image_path: Path, style: str = "fill") -> None:
    image_path = image_path.expanduser().resolve()
    if not image_path.exists():
        raise FileNotFoundError(str(image_path))

    _set_reg_wallpaper_style(style)

    path_str = os.fspath(image_path)
    result = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER,
        0,
        path_str,
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
    )

    if not result:
        raise ctypes.WinError()


# ---------------------------------------------------------------------------
# Screen resolution
# ---------------------------------------------------------------------------


def get_primary_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary display in physical pixels.

    Makes the process DPI-aware so the returned size is not scaled
    (common on 125%/150% display scaling).
    """

    try:
        user32 = ctypes.windll.user32

        # Try to become DPI-aware to get real pixel dimensions.
        try:
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
