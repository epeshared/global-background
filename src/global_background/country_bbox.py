from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .system_proxy import system_proxy_env_for_url


# Rough built-in fallbacks (lat_min, lon_min, lat_max, lon_max)
# Used only when online resolution is unavailable.
_FALLBACK_BBOX_BY_ISO2: dict[str, tuple[float, float, float, float]] = {
    "CN": (18.0, 73.0, 54.0, 135.0),
    "US": (24.5, -125.0, 49.5, -66.5),
    "JP": (24.0, 122.0, 46.0, 146.0),
    "KR": (33.0, 124.5, 39.5, 131.0),
    "SG": (1.1, 103.6, 1.5, 104.1),
    "GB": (49.8, -8.7, 60.9, 2.1),
    "DE": (47.2, 5.9, 55.1, 15.1),
    "FR": (41.3, -5.2, 51.2, 9.7),
    "IN": (6.5, 68.0, 35.7, 97.5),
    "AU": (-44.0, 112.0, -10.0, 154.0),
}


def resolve_country_bbox_latlon(
    *,
    country_code: str | None,
    country_name: str | None,
    timeout_s: float = 20.0,
) -> tuple[float, float, float, float]:
    """Best-effort resolve a country's bbox as (lat_min, lon_min, lat_max, lon_max).

    Strategy:
    1) Try Nominatim (OpenStreetMap) using country_name.
    2) Fallback to a small built-in bbox table using ISO2 country_code.

    This function is dependency-free and works through corporate proxies (urllib honors env vars).
    """

    name = (country_name or "").strip()
    code = (country_code or "").strip().upper()

    if name:
        bbox = _try_nominatim_country_bbox(name=name, timeout_s=timeout_s)
        if bbox is not None:
            return bbox

    if code and code in _FALLBACK_BBOX_BY_ISO2:
        return _FALLBACK_BBOX_BY_ISO2[code]

    raise RuntimeError(
        "Unable to resolve country bbox. Provide region.country_bbox_latlon in config, "
        "or ensure country_name/country_code is available."
    )


def _try_nominatim_country_bbox(*, name: str, timeout_s: float) -> tuple[float, float, float, float] | None:
    # Nominatim returns boundingbox = [south_lat, north_lat, west_lon, east_lon]
    # Keep this request simple; some corporate networks may block it.
    params = {
        "country": name,
        "format": "json",
        "limit": "1",
        "addressdetails": "0",
    }
    url = "https://nominatim.openstreetmap.org/search?" + urlencode(params)
    req = Request(
        url,
        headers={
            "User-Agent": "global-background/0.1 (country bbox resolver)",
        },
    )

    try:
        with system_proxy_env_for_url(req.full_url):
            with urlopen(req, timeout=timeout_s) as resp:
                payload = resp.read().decode("utf-8", errors="replace")
        data = json.loads(payload)
        if not isinstance(data, list) or not data:
            return None
        bb = data[0].get("boundingbox")
        if not (isinstance(bb, list) and len(bb) == 4):
            return None
        south = float(bb[0])
        north = float(bb[1])
        west = float(bb[2])
        east = float(bb[3])
        return (south, west, north, east)
    except Exception:
        return None