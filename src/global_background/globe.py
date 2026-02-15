from __future__ import annotations

import math
import random
from io import BytesIO


try:
    from PIL import Image  # type: ignore
except Exception:  # Pillow not installed
    Image = None  # type: ignore


def render_orthographic_globe(
    *,
    source_image_bytes: bytes,
    center_lat: float,
    center_lon: float,
    out_width: int,
    out_height: int,
    background_style: str = "solid",
    background_rgb: tuple[int, int, int] = (0, 0, 0),
    background_rgb2: tuple[int, int, int] = (0, 0, 0),
    background_stars: bool = False,
) -> "Image.Image":
    """Render an orthographic ("globe") view from an equirectangular world map.

    - source: equirectangular lon/lat map (global)
    - center: degrees, where the globe is facing

    Requires Pillow.
    """

    if Image is None:
        raise RuntimeError("Globe rendering requires Pillow. Install extras: python -m pip install -e .[full]")

    if out_width <= 0 or out_height <= 0:
        raise ValueError("out_width/out_height must be positive")

    src = Image.open(BytesIO(source_image_bytes)).convert("RGB")
    src.load()
    src_w, src_h = src.size
    src_px = src.load()

    dst = _make_background(
        width=out_width,
        height=out_height,
        style=background_style,
        rgb1=background_rgb,
        rgb2=background_rgb2,
        stars=background_stars,
    )
    dst_px = dst.load()

    # Globe radius and center
    cx = (out_width - 1) * 0.5
    cy = (out_height - 1) * 0.5
    r = min(out_width, out_height) * 0.47
    if r <= 1:
        return dst

    # Precompute basis for the chosen center
    lat0 = math.radians(center_lat)
    lon0 = math.radians(center_lon)
    cos_lat0 = math.cos(lat0)
    sin_lat0 = math.sin(lat0)
    cos_lon0 = math.cos(lon0)
    sin_lon0 = math.sin(lon0)

    # Center vector C, east E, north N
    c_x = cos_lat0 * cos_lon0
    c_y = cos_lat0 * sin_lon0
    c_z = sin_lat0

    e_x = -sin_lon0
    e_y = cos_lon0
    e_z = 0.0

    n_x = -sin_lat0 * cos_lon0
    n_y = -sin_lat0 * sin_lon0
    n_z = cos_lat0

    inv_r = 1.0 / r
    two_pi = 2.0 * math.pi

    for y in range(out_height):
        dy = (y - cy) * inv_r
        # screen y down => up is -dy
        uy = -dy
        dy2 = dy * dy

        for x in range(out_width):
            dx = (x - cx) * inv_r
            rr = dx * dx + dy2
            if rr > 1.0:
                continue

            z = math.sqrt(1.0 - rr)

            # vector in global coords: dx*E + uy*N + z*C
            vx = dx * e_x + uy * n_x + z * c_x
            vy = dx * e_y + uy * n_y + z * c_y
            vz = dx * e_z + uy * n_z + z * c_z

            # to lat/lon
            lat = math.asin(max(-1.0, min(1.0, vz)))
            lon = math.atan2(vy, vx)

            # map to source pixels
            u = (lon + math.pi) / two_pi
            v = (math.pi * 0.5 - lat) / math.pi

            sx = int(u * (src_w - 1))
            sy = int(v * (src_h - 1))
            dst_px[x, y] = src_px[sx, sy]

    return dst


def _make_background(
    *,
    width: int,
    height: int,
    style: str,
    rgb1: tuple[int, int, int],
    rgb2: tuple[int, int, int],
    stars: bool,
) -> "Image.Image":
    if Image is None:
        raise RuntimeError("Background rendering requires Pillow")

    style = (style or "solid").strip().lower()
    if style not in {"solid", "gradient"}:
        style = "solid"

    if style == "solid":
        img = Image.new("RGB", (width, height), rgb1)
    else:
        # Radial gradient: rgb1 near center, rgb2 near corners.
        img = Image.new("RGB", (width, height))
        px = img.load()
        cx = (width - 1) * 0.5
        cy = (height - 1) * 0.5
        # normalize to corner distance
        max_d = math.sqrt(cx * cx + cy * cy) or 1.0
        for y in range(height):
            dy = y - cy
            for x in range(width):
                dx = x - cx
                t = math.sqrt(dx * dx + dy * dy) / max_d
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                # Slight curve so the inner dark-blue is more noticeable.
                t = t**0.85
                r = int(rgb1[0] + (rgb2[0] - rgb1[0]) * t)
                g = int(rgb1[1] + (rgb2[1] - rgb1[1]) * t)
                b = int(rgb1[2] + (rgb2[2] - rgb1[2]) * t)
                px[x, y] = (r, g, b)

    if stars:
        # Subtle star field; deterministic for a given resolution.
        rnd = random.Random(width * 1000003 + height)
        n = max(50, int(width * height * 0.00003))
        px = img.load()
        for _ in range(n):
            x = rnd.randrange(0, width)
            y = rnd.randrange(0, height)
            # small chance of brighter star
            v = 160 + rnd.randrange(0, 96)
            if rnd.random() < 0.08:
                v = 230 + rnd.randrange(0, 26)
            r = min(255, v)
            g = min(255, int(v * 0.98))
            b = min(255, int(v * 0.92))
            px[x, y] = (r, g, b)

    return img


def make_background(
    *,
    width: int,
    height: int,
    style: str = "solid",
    rgb1: tuple[int, int, int] = (0, 0, 0),
    rgb2: tuple[int, int, int] = (0, 0, 0),
    stars: bool = False,
) -> "Image.Image":
    """Create a space-like background (solid or radial gradient + optional stars).

    Requires Pillow.
    """

    return _make_background(width=width, height=height, style=style, rgb1=rgb1, rgb2=rgb2, stars=stars)


def encode_image(img: "Image.Image", fmt: str, quality: int) -> bytes:
    if Image is None:
        raise RuntimeError("encode_image requires Pillow")

    fmt2 = fmt.lower().strip()
    buf = BytesIO()
    if fmt2 in {"jpg", "jpeg"}:
        img.convert("RGB").save(buf, format="JPEG", quality=int(quality), optimize=True)
    elif fmt2 == "png":
        img.save(buf, format="PNG", optimize=True)
    else:
        raise ValueError(f"Unsupported output format: {fmt}")
    return buf.getvalue()