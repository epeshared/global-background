from __future__ import annotations

from dataclasses import dataclass

import json
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class GeoLocation:
    name: str | None
    lat: float
    lon: float
    country_code: str | None = None
    country_name: str | None = None


def get_location_from_ip(timeout_s: float = 10.0) -> GeoLocation:
    """Best-effort IP geolocation without API key.

    Note: Accuracy depends on your network; may resolve to ISP location.
    """

    # ipapi.co: simple unauthenticated endpoint
    req = Request("https://ipapi.co/json/", headers={"User-Agent": "global-background/0.1"})
    with urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))

    lat = float(data["latitude"])
    lon = float(data["longitude"])
    city = data.get("city")
    region = data.get("region")
    country = data.get("country_name")
    country_code = data.get("country_code")

    parts = [p for p in [city, region, country] if p]
    name = ", ".join(parts) if parts else None

    return GeoLocation(
        name=name,
        lat=lat,
        lon=lon,
        country_code=str(country_code).upper() if country_code else None,
        country_name=str(country) if country else None,
    )
