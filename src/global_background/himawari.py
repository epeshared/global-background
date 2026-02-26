from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from io import BytesIO

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .system_proxy import system_proxy_env_for_url


HIMAWARI_DL_BASE = "https://himawari8-dl.nict.go.jp/himawari.asia/img"

try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None  # type: ignore


@dataclass(frozen=True)
class HimawariFullDiskRequest:
    product: str  # e.g. "FULL_24h"
    band: str | None  # e.g. "B13" (infrared). Some products (e.g. D531106) have no band segment.
    level_d: int  # 1,2,4,8 (number of tiles per side)
    tile_size: int = 550


def _download_tile_bytes(*, url: str, timeout_s: float) -> tuple[bytes, str]:
    http_req = Request(url, headers={"User-Agent": "global-background/0.1"})
    with system_proxy_env_for_url(http_req.full_url):
        with urlopen(http_req, timeout=timeout_s) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read()
    return data, ctype



def _is_placeholder_tileset(*, corner: bytes, center: bytes) -> bool:
    # In some enterprise environments, blocked URLs may be replaced by a tiny PNG that is
    # byte-identical across requests/tiles.
    return (not corner) or (not center) or (corner == center)


def fetch_latest_full_disk_png(
    req: HimawariFullDiskRequest,
    *,
    timeout_s: float = 30.0,
    max_lookback_minutes: int = 240,
    step_minutes: int = 10,
    target_utc: dt.datetime | None = None,
) -> tuple[bytes, dt.datetime, str]:
    """Fetch the latest available Himawari full-disk PNG.

    Himawari URLs are time-stamped and don't always provide a stable "latest" endpoint.
    We probe by stepping backwards in time (UTC) until we find an existing frame.

    If *target_utc* is given, probing starts from that time instead of now().
    This allows fetching historical frames (e.g. for the 24-hour slideshow backfill).

    Returns: (png_bytes, timestamp_utc, url)
    """

    if step_minutes <= 0:
        raise ValueError("step_minutes must be positive")
    if max_lookback_minutes < 0:
        raise ValueError("max_lookback_minutes must be >= 0")

    base = target_utc.astimezone(dt.timezone.utc) if target_utc is not None else dt.datetime.now(dt.timezone.utc)
    # Round down to step
    minute = (base.minute // step_minutes) * step_minutes
    cursor = base.replace(minute=minute, second=0, microsecond=0)

    tries = max(1, (max_lookback_minutes // step_minutes) + 1)
    last_exc: Exception | None = None

    for _ in range(tries):
        # Probe existence by fetching tile (0,0)
        probe_url = _build_tile_url(req=req, ts_utc=cursor, x=0, y=0)
        try:
            tile00, ctype00 = _download_tile_bytes(url=probe_url, timeout_s=timeout_s)
            if "image" not in ctype00:
                raise RuntimeError(f"Unexpected content-type: {ctype00}")

            # If a proxy replaces tiles with a tiny placeholder image or HTML->PNG wrapper,
            # looking back in time won't help. Fail fast so callers can fall back.
            if len(tile00) < 5_000:
                raise RuntimeError(f"Himawari returned unexpectedly small tile payload ({len(tile00)} bytes)")

            if int(req.level_d) > 1:
                d = int(req.level_d)
                cx = d // 2
                cy = d // 2
                center_url = _build_tile_url(req=req, ts_utc=cursor, x=cx, y=cy)
                tilec, ctypec = _download_tile_bytes(url=center_url, timeout_s=timeout_s)
                if "image" not in ctypec:
                    raise RuntimeError(f"Unexpected content-type: {ctypec}")

                if _is_placeholder_tileset(corner=tile00, center=tilec):
                    h = hashlib.sha256(tile00).hexdigest()[:16] if tile00 else "<empty>"
                    raise RuntimeError(
                        "Himawari tiles appear to be blocked/replaced by a proxy placeholder: "
                        f"corner and center tiles are byte-identical (len={len(tile00)}, sha256~{h}). "
                        "Try allowlisting himawari8-dl.nict.go.jp on your proxy or use another provider (e.g. GIBS)."
                    )

            # Exists. Fetch all tiles and stitch.
            png = _download_and_stitch(req=req, ts_utc=cursor, timeout_s=timeout_s)
            return png, cursor, probe_url
        except HTTPError as exc:
            # Most common: 404 for non-existent timestamps
            last_exc = exc
        except URLError as exc:
            last_exc = exc
        except Exception as exc:
            # If we detect proxy placeholder behavior, don't keep probing older timestamps.
            if isinstance(exc, RuntimeError):
                msg = str(exc)
                if (
                    "blocked/replaced by a proxy placeholder" in msg
                    or "unexpectedly small tile payload" in msg
                    or "unexpectedly small payload" in msg
                ):
                    raise
            last_exc = exc

        cursor -= dt.timedelta(minutes=step_minutes)

    raise RuntimeError(f"Unable to find a recent Himawari frame (last error: {last_exc!r})")


def _build_tile_url(*, req: HimawariFullDiskRequest, ts_utc: dt.datetime, x: int, y: int) -> str:
    # Pattern (banded):
    #   https://.../img/FULL_24h/B13/{Nd}/550/YYYY/MM/DD/HHMMSS_x_y.png
    # Pattern (unbanded):
    #   https://.../img/D531106/{Nd}/550/YYYY/MM/DD/HHMMSS_x_y.png
    # where N is number of tiles per side (1,2,4,8,...)
    ts_utc = ts_utc.astimezone(dt.timezone.utc)
    stamp = ts_utc.strftime("%H%M%S")

    band = (req.band or "").strip()
    mid = f"{req.product}/{band}" if band else f"{req.product}"
    return (
        f"{HIMAWARI_DL_BASE}/{mid}/{int(req.level_d)}d/{int(req.tile_size)}/"
        f"{ts_utc.year:04d}/{ts_utc.month:02d}/{ts_utc.day:02d}/{stamp}_{int(x)}_{int(y)}.png"
    )


def _download_and_stitch(*, req: HimawariFullDiskRequest, ts_utc: dt.datetime, timeout_s: float) -> bytes:
    if int(req.level_d) <= 1:
        # Single-tile image; just download the one tile
        url = _build_tile_url(req=req, ts_utc=ts_utc, x=0, y=0)
        data, ctype = _download_tile_bytes(url=url, timeout_s=timeout_s)
        if "image" not in ctype:
            raise RuntimeError(f"Unexpected content-type: {ctype}")
        if len(data) < 5_000:
            raise RuntimeError(f"Himawari returned unexpectedly small payload ({len(data)} bytes)")
        return data

    if Image is None:
        raise RuntimeError(
            "Himawari high-resolution tiled download requires Pillow for stitching tiles. "
            "Install: python -m pip install Pillow"
        )

    d = int(req.level_d)
    tile = int(req.tile_size)
    full_size = (d * tile, d * tile)
    canvas = Image.new("RGB", full_size)

    # Early placeholder detection: compare corner vs center-ish tile.
    corner_url = _build_tile_url(req=req, ts_utc=ts_utc, x=0, y=0)
    cx = d // 2
    cy = d // 2
    center_url = _build_tile_url(req=req, ts_utc=ts_utc, x=cx, y=cy)
    corner_bytes, corner_ctype = _download_tile_bytes(url=corner_url, timeout_s=timeout_s)
    center_bytes, center_ctype = _download_tile_bytes(url=center_url, timeout_s=timeout_s)
    if "image" not in corner_ctype or "image" not in center_ctype:
        raise RuntimeError(f"Unexpected content-type(s): corner={corner_ctype} center={center_ctype}")
    if _is_placeholder_tileset(corner=corner_bytes, center=center_bytes):
        h = hashlib.sha256(corner_bytes).hexdigest()[:16] if corner_bytes else "<empty>"
        raise RuntimeError(
            "Himawari tiles appear to be blocked/replaced by a proxy placeholder: "
            f"corner and center tiles are byte-identical (len={len(corner_bytes)}, sha256~{h}). "
            "Try allowlisting himawari8-dl.nict.go.jp on your proxy or use another provider (e.g. GIBS)."
        )

    preloaded: dict[tuple[int, int], bytes] = {(0, 0): corner_bytes, (cx, cy): center_bytes}

    for y in range(d):
        for x in range(d):
            data = preloaded.get((x, y))
            if data is None:
                url = _build_tile_url(req=req, ts_utc=ts_utc, x=x, y=y)
                data, ctype = _download_tile_bytes(url=url, timeout_s=timeout_s)
                if "image" not in ctype:
                    raise RuntimeError(f"Unexpected content-type: {ctype}")

            if len(data) < 5_000:
                raise RuntimeError(f"Himawari returned unexpectedly small tile payload ({len(data)} bytes)")
            img = Image.open(BytesIO(data)).convert("RGB")
            img.load()
            canvas.paste(img, (x * tile, y * tile))

    out = BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()