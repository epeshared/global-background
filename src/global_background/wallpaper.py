from __future__ import annotations

import ctypes
import os
from pathlib import Path

import winreg

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02


def _set_reg_wallpaper_style(style: str) -> None:
    style = style.lower().strip()

    # Values based on Windows behavior for Control Panel\Desktop
    # https://stackoverflow.com/questions/1061678/change-desktop-wallpaper-using-python
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

    # SystemParametersInfoW expects a null-terminated wide string
    path_str = os.fspath(image_path)
    result = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER,
        0,
        path_str,
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
    )

    if not result:
        raise ctypes.WinError()
