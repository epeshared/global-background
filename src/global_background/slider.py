from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .system_proxy import system_proxy_env_for_url

try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None  # type: ignore

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage  # pragma: no cover


SLIDER_BASE = "https://slider.cira.colostate.edu"


@dataclass(frozen=True)
class SliderFullDiskRequest:
    satellite: str = "himawari"  # "himawari" | "gk2a"
    sector: str = "full_disk"  # currently only this is supported
    product: str = "geocolor"  # e.g. geocolor | natural_color | band_13 ...

    # Max imagery pyramid level to use. Levels map to tiles_per_side = 2**level.
    # Typical levels observed: 0..4.
    max_level: int = 3

    # Heuristic: pick the smallest level whose stitched square is >= this many px.
    # If None, it will be derived from the requested wallpaper size.
    min_square_px: int | None = None


def _norm_token(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_")


def _latest_times_url(req: SliderFullDiskRequest) -> str:
    sat = _norm_token(req.satellite)
    sector = _norm_token(req.sector)
    product = _norm_token(req.product)
    return f"{SLIDER_BASE}/data/json/{sat}/{sector}/{product}/latest_times.json"


def _imagery_dirname(req: SliderFullDiskRequest) -> str:
    # Matches paths shown on the SLIDER site.
    # Example: himawari---full_disk
    sat = _norm_token(req.satellite)
    sector = _norm_token(req.sector)
    return f"{sat}---{sector}"


def _parse_timestamp_int(ts_int: int) -> dt.datetime:
    s = str(int(ts_int))
    # Expected: YYYYMMDDHHMMSS
    return dt.datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)


def _download_json(url: str, *, timeout_s: float) -> dict:
    http_req = Request(url, headers={"User-Agent": "global-background/0.1", "Cache-Control": "no-cache"})
    with system_proxy_env_for_url(http_req.full_url):
        with urlopen(http_req, timeout=float(timeout_s)) as resp:
            data = resp.read()
    return json.loads(data.decode("utf-8"))


def fetch_latest_timestamp_utc(req: SliderFullDiskRequest, *, timeout_s: float = 30.0) -> dt.datetime:
    data = _download_json(_latest_times_url(req), timeout_s=timeout_s)
    ts = data.get("timestamps_int")
    if not isinstance(ts, list) or not ts:
        raise RuntimeError(f"SLIDER latest_times.json missing timestamps_int: {data!r}")
    return _parse_timestamp_int(int(ts[0]))


def _tile_url(*, req: SliderFullDiskRequest, ts_utc: dt.datetime, level: int, x: int, y: int) -> str:
    ts_utc = ts_utc.astimezone(dt.timezone.utc)
    stamp = ts_utc.strftime("%Y%m%d%H%M%S")
    yyyy = ts_utc.strftime("%Y")
    mm = ts_utc.strftime("%m")
    dd = ts_utc.strftime("%d")

    product = _norm_token(req.product)
    dirname = _imagery_dirname(req)

    return (
        f"{SLIDER_BASE}/data/imagery/{yyyy}/{mm}/{dd}/{dirname}/{product}/{stamp}/"
        f"{int(level):02d}/{int(x):03d}_{int(y):03d}.png"
    )


def _download_tile_bytes(url: str, *, timeout_s: float, cache_bust: bool = True) -> bytes:
    if cache_bust:
        url = f"{url}?_={int(dt.datetime.now(dt.timezone.utc).timestamp())}"
    http_req = Request(url, headers={"User-Agent": "global-background/0.1", "Cache-Control": "no-cache"})
    with system_proxy_env_for_url(http_req.full_url):
        with urlopen(http_req, timeout=float(timeout_s)) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read()
    if "image" not in ctype:
        raise RuntimeError(f"Unexpected content-type: {ctype}")
    if not data:
        raise RuntimeError("Empty tile payload")
    return data


def _mean_abs_diff_edge(a: "PILImage", b: "PILImage", *, vertical: bool) -> float:
    # Compare boundary pixels to detect correct tile adjacency.
    w, h = a.size
    if vertical:
        a_edge = a.crop((w - 1, 0, w, h))
        b_edge = b.crop((0, 0, 1, h))
    else:
        a_edge = a.crop((0, h - 1, w, h))
        b_edge = b.crop((0, 0, w, 1))

    a_px = list(a_edge.getdata())
    b_px = list(b_edge.getdata())
    if not a_px or not b_px:
        return 0.0

    total = 0
    for (r1, g1, b1), (r2, g2, b2) in zip(a_px, b_px):
        total += abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
    return total / (len(a_px) * 3)


def _infer_swap_xy(
    *, req: SliderFullDiskRequest, ts_utc: dt.datetime, level: int, timeout_s: float
) -> bool:
    """Infer whether SLIDER's tile indices are effectively swapped.

    Empirically, some SLIDER full-disk products use (x,y) naming on disk but the
    imagery grid aligns as if x/y were swapped. When stitched with the wrong axis
    convention, the earth looks "shattered" into misordered blocks.

    We detect this cheaply by sampling a center tile and its right/down neighbors
    and comparing boundary continuity under both hypotheses.
    """

    if Image is None:
        return False

    tiles = 2**int(level)
    if tiles <= 1:
        return False

    cx = min(max(0, tiles // 2), tiles - 2)
    cy = min(max(0, tiles // 2), tiles - 2)

    def load_tile(x: int, y: int) -> "PILImage":
        u = _tile_url(req=req, ts_utc=ts_utc, level=level, x=x, y=y)
        b = _download_tile_bytes(u, timeout_s=timeout_s)
        img = Image.open(BytesIO(b)).convert("RGB")
        img.load()
        return img

    # URL tiles (x,y)
    c = load_tile(cx, cy)
    right = load_tile(cx + 1, cy)
    down = load_tile(cx, cy + 1)

    # Normal hypothesis: right neighbor uses (x+1,y) and down uses (x,y+1)
    normal = _mean_abs_diff_edge(c, right, vertical=True) + _mean_abs_diff_edge(c, down, vertical=False)

    # Swapped hypothesis: right neighbor would actually be the (x,y+1) URL tile,
    # and down neighbor would be (x+1,y).
    swapped = _mean_abs_diff_edge(c, down, vertical=True) + _mean_abs_diff_edge(c, right, vertical=False)

    return swapped < normal


def _pick_level(*, req: SliderFullDiskRequest, target_max_dim_px: int) -> int:
    # SLIDER uses a pyramid where each level doubles the tiles per side.
    # We don't know the exact tile size a priori (commonly 688x688), so we use a
    # conservative derivation: request the smallest level that is likely to avoid
    # upscaling for the wallpaper size.
    #
    # tile_size * 2**level >= target_max_dim
    # tile_size is discovered from (0,0) once.

    max_level = max(0, int(req.max_level))
    if req.min_square_px is not None:
        target_max_dim_px = max(int(req.min_square_px), 1)

    # Start optimistic: assume ~688px tiles.
    tile_guess = 688
    desired = 0
    while desired < max_level and (tile_guess * (2**desired)) < target_max_dim_px:
        desired += 1
    return int(desired)


def fetch_latest_full_disk_png(
    req: SliderFullDiskRequest,
    *,
    timeout_s: float = 30.0,
    target_max_dim_px: int = 3840,
) -> tuple[bytes, dt.datetime, str]:
    """Fetch the latest SLIDER full-disk frame as a stitched PNG.

    Returns: (png_bytes, timestamp_utc, sample_url)
    """

    ts_utc = fetch_latest_timestamp_utc(req, timeout_s=timeout_s)

    # Without Pillow we can't stitch tiles; force level=0 (single tile).
    if Image is None:
        desired_level = 0
    else:
        desired_level = _pick_level(req=req, target_max_dim_px=int(target_max_dim_px))

    # Probe from desired downwards to find a level that exists.
    last_exc: Exception | None = None
    for level in range(desired_level, -1, -1):
        tiles = 2**level
        probe00 = _tile_url(req=req, ts_utc=ts_utc, level=level, x=0, y=0)
        probell = _tile_url(req=req, ts_utc=ts_utc, level=level, x=tiles - 1, y=tiles - 1)
        try:
            _ = _download_tile_bytes(probe00, timeout_s=timeout_s)
            _ = _download_tile_bytes(probell, timeout_s=timeout_s)
            desired_level = level
            break
        except HTTPError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            last_exc = exc
            continue
    else:
        raise RuntimeError(f"Unable to fetch SLIDER tiles (last error: {last_exc!r})")

    level = desired_level
    tiles = 2**level

    # Single tile: return as-is.
    sample_url = _tile_url(req=req, ts_utc=ts_utc, level=level, x=0, y=0)
    if tiles == 1:
        data = _download_tile_bytes(sample_url, timeout_s=timeout_s)
        return data, ts_utc, sample_url

    # From here on we know Image is available (tiles > 1).

    swap_xy = _infer_swap_xy(req=req, ts_utc=ts_utc, level=level, timeout_s=timeout_s)

    def url_for_display_xy(x: int, y: int) -> str:
        # If SLIDER's (x,y) on disk is effectively transposed, swap when requesting.
        if swap_xy:
            return _tile_url(req=req, ts_utc=ts_utc, level=level, x=y, y=x)
        return _tile_url(req=req, ts_utc=ts_utc, level=level, x=x, y=y)

    # Preload corner + center for fast proxy-placeholder detection.
    cx = tiles // 2
    cy = tiles // 2
    corner_url = url_for_display_xy(0, 0)
    center_url = url_for_display_xy(cx, cy)

    corner_bytes = _download_tile_bytes(corner_url, timeout_s=timeout_s)
    center_bytes = _download_tile_bytes(center_url, timeout_s=timeout_s)

    # If a proxy replaces all tiles with a single placeholder image, corner==center.
    if corner_bytes == center_bytes:
        h = hashlib.sha256(corner_bytes).hexdigest()[:16] if corner_bytes else "<empty>"
        raise RuntimeError(
            "SLIDER tiles appear to be blocked/replaced by a proxy placeholder: "
            f"corner and center tiles are byte-identical (len={len(corner_bytes)}, sha256~{h})."
        )

    corner_img = Image.open(BytesIO(corner_bytes)).convert("RGB")
    corner_img.load()
    tile_w, tile_h = corner_img.size
    if tile_w <= 0 or tile_h <= 0:
        raise RuntimeError(f"Invalid tile size: {corner_img.size}")

    full_size = (tile_w * tiles, tile_h * tiles)
    canvas = Image.new("RGB", full_size)

    preloaded: dict[tuple[int, int], bytes] = {(0, 0): corner_bytes, (cx, cy): center_bytes}

    for y in range(tiles):
        for x in range(tiles):
            data = preloaded.get((x, y))
            if data is None:
                url = url_for_display_xy(x, y)
                data = _download_tile_bytes(url, timeout_s=timeout_s)

            img = Image.open(BytesIO(data)).convert("RGB")
            img.load()
            canvas.paste(img, (x * tile_w, y * tile_h))

    out = BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    # sample_url is informational only.
    sample_url = corner_url
    return out.getvalue(), ts_utc, sample_url
