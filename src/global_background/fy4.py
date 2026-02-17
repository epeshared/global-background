"""FY-4A / FY-4B full-disk image fetcher.

Downloads the latest full-disk JPEG from China's National Satellite
Meteorological Center (NSMC) at img.nsmc.org.cn.

Available endpoints (verified 2026-02):
  FY-4A  MTCC (multi-channel true-colour composite, ~2200x2200, ~800 KB)
    http://img.nsmc.org.cn/CLOUDIMAGE/FY4A/MTCC/FY4A_DISK.jpg

  FY-4B  GCLR (AGRI geo-colour, ~11000x12000, ~11 MB)
    http://img.nsmc.org.cn/CLOUDIMAGE/FY4B/AGRI/GCLR/FY4B_DISK_GCLR.jpg

These URLs always serve the **latest** image; there is no timestamp API.
We parse the Last-Modified header (if present) for the image timestamp.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

from .system_proxy import system_proxy_env_for_url


# ---------------------------------------------------------------------------
# Known endpoints
# ---------------------------------------------------------------------------

_ENDPOINTS: dict[tuple[str, str], str] = {
    # (satellite, product) -> URL
    ("fy4a", "mtcc"): "http://img.nsmc.org.cn/CLOUDIMAGE/FY4A/MTCC/FY4A_DISK.jpg",
    ("fy4b", "gclr"): "http://img.nsmc.org.cn/CLOUDIMAGE/FY4B/AGRI/GCLR/FY4B_DISK_GCLR.jpg",
}


@dataclass(frozen=True)
class FY4FullDiskRequest:
    satellite: str = "fy4a"  # "fy4a" | "fy4b"
    product: str = "mtcc"    # "mtcc" (FY4A) | "gclr" (FY4B)


def _resolve_url(req: FY4FullDiskRequest) -> str:
    sat = req.satellite.strip().lower()
    prod = req.product.strip().lower()
    url = _ENDPOINTS.get((sat, prod))
    if url is None:
        raise ValueError(
            f"Unknown FY-4 endpoint: satellite={sat!r} product={prod!r}. "
            f"Supported: {list(_ENDPOINTS.keys())}"
        )
    return url


def fetch_latest_full_disk_jpg(
    req: FY4FullDiskRequest,
    *,
    timeout_s: float = 30.0,
) -> tuple[bytes, dt.datetime, str]:
    """Fetch the latest FY-4 full-disk JPEG.

    Returns: (jpeg_bytes, timestamp_utc, url)
    """

    url = _resolve_url(req)

    http_req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) global-background/0.1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    with system_proxy_env_for_url(url):
        with urlopen(http_req, timeout=float(timeout_s)) as resp:
            data = resp.read()

    if not data or len(data) < 10_000:
        raise RuntimeError(f"FY-4 response too small ({len(data)} bytes), likely a placeholder")

    # Try to extract timestamp from Last-Modified header
    ts_utc = dt.datetime.now(dt.timezone.utc)
    lm = resp.headers.get("Last-Modified")
    if lm:
        try:
            ts_utc = parsedate_to_datetime(lm).astimezone(dt.timezone.utc)
        except Exception:
            pass

    return data, ts_utc, url
