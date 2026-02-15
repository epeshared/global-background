from __future__ import annotations

import struct
from pathlib import Path


def write_solid_bmp(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    """Write a simple 24-bit BMP (BGR) with a solid color.

    This is dependency-free (no Pillow), useful for offline testing.
    """

    if width <= 0 or height <= 0:
        raise ValueError("width/height must be positive")

    r, g, b = (int(rgb[0]) & 0xFF, int(rgb[1]) & 0xFF, int(rgb[2]) & 0xFF)

    # Each row is padded to 4-byte boundary
    row_bytes = width * 3
    padding = (4 - (row_bytes % 4)) % 4
    stride = row_bytes + padding

    pixel_data_size = stride * height
    file_size = 14 + 40 + pixel_data_size

    # BITMAPFILEHEADER
    bfType = b"BM"
    bfSize = file_size
    bfReserved1 = 0
    bfReserved2 = 0
    bfOffBits = 14 + 40

    # BITMAPINFOHEADER
    biSize = 40
    biWidth = width
    biHeight = height  # positive => bottom-up
    biPlanes = 1
    biBitCount = 24
    biCompression = 0
    biSizeImage = pixel_data_size
    biXPelsPerMeter = 2835
    biYPelsPerMeter = 2835
    biClrUsed = 0
    biClrImportant = 0

    header = struct.pack(
        "<2sIHHI",
        bfType,
        bfSize,
        bfReserved1,
        bfReserved2,
        bfOffBits,
    )
    info = struct.pack(
        "<IIIHHIIIIII",
        biSize,
        biWidth,
        biHeight,
        biPlanes,
        biBitCount,
        biCompression,
        biSizeImage,
        biXPelsPerMeter,
        biYPelsPerMeter,
        biClrUsed,
        biClrImportant,
    )

    # Bottom-up rows
    pixel = bytes([b, g, r])
    row = pixel * width + (b"\x00" * padding)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(header)
        f.write(info)
        for _ in range(height):
            f.write(row)
