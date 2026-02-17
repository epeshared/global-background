from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

from .system_proxy import system_proxy_env_for_url


@dataclass(frozen=True)
class GoesFullDiskRequest:
    satellite: str  # "GOES16" | "GOES18" (case-insensitive)
    product: str = "GEOCOLOR"  # currently only this product is supported
    size: int = 5424  # square output size (e.g. 678, 1808, 5424, 10848)


def _normalize_satellite(value: str) -> str:
    s = (value or "").strip().upper()
    if not s:
        return "GOES18"
    if s.startswith("GOES"):
        return s
    if s in {"16", "18"}:
        return f"GOES{s}"
    return s


def _build_url(req: GoesFullDiskRequest) -> str:
    satellite = _normalize_satellite(req.satellite)
    product = (req.product or "GEOCOLOR").strip().upper()
    # Directory names are uppercase on the CDN.
    # Example:
    #   https://cdn.star.nesdis.noaa.gov/GOES18/ABI/FD/GEOCOLOR/5424x5424.jpg
    return f"https://cdn.star.nesdis.noaa.gov/{satellite}/ABI/FD/{product}/{int(req.size)}x{int(req.size)}.jpg"


def fetch_latest_full_disk_jpg(
    req: GoesFullDiskRequest,
    *,
    timeout_s: float = 30.0,
    cache_bust: bool = True,
) -> tuple[bytes, dt.datetime, str]:
    url = _build_url(req)
    if cache_bust:
        # Some proxies aggressively cache the "latest" JPEG. A harmless query string
        # usually forces a revalidation/fresh fetch.
        url = f"{url}?_={int(dt.datetime.now(dt.timezone.utc).timestamp())}"

    http_req = Request(
        url,
        headers={
            "User-Agent": "global-background/0.1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with system_proxy_env_for_url(http_req.full_url):
        with urlopen(http_req, timeout=float(timeout_s)) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            last_modified = resp.headers.get("Last-Modified")
            data = resp.read()

    if "image" not in ctype:
        raise RuntimeError(f"Unexpected content-type: {ctype}")

    # Fail fast on obvious proxy placeholder / error-image behavior.
    if len(data) < 50_000:
        raise RuntimeError(f"GOES returned unexpectedly small payload ({len(data)} bytes)")

    ts_utc = dt.datetime.now(dt.timezone.utc)
    if last_modified:
        try:
            ts = parsedate_to_datetime(last_modified)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            ts_utc = ts.astimezone(dt.timezone.utc)
        except Exception:
            pass

    return data, ts_utc, url

