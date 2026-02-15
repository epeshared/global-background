from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


GIBS_WMS_EPSG4326_BEST = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"


@dataclass(frozen=True)
class GibsRequest:
    layer: str
    date: dt.date
    bbox_latlon: tuple[float, float, float, float]  # (lat_min, lon_min, lat_max, lon_max)
    width: int
    height: int
    image_format: str  # "jpg" or "png"


def _wms_format(fmt: str) -> str:
    fmt = fmt.lower()
    if fmt in {"jpg", "jpeg"}:
        return "image/jpeg"
    if fmt == "png":
        return "image/png"
    raise ValueError(f"Unsupported image format: {fmt}")


def build_wms_params(req: GibsRequest) -> dict[str, str]:
    lat_min, lon_min, lat_max, lon_max = req.bbox_latlon

    # Important: Use WMS 1.1.1 to avoid EPSG:4326 axis-order ambiguity in WMS 1.3.0.
    # For 1.1.1, BBOX is consistently lon,lat order.
    bbox = f"{lon_min},{lat_min},{lon_max},{lat_max}"

    return {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.1.1",
        "LAYERS": req.layer,
        "STYLES": "",
        "FORMAT": _wms_format(req.image_format),
        "TRANSPARENT": "FALSE",
        "WIDTH": str(req.width),
        "HEIGHT": str(req.height),
        "SRS": "EPSG:4326",
        "BBOX": bbox,
        "TIME": req.date.isoformat(),
    }


def fetch_wms_image_bytes(
    req: GibsRequest,
    timeout_s: float = 30.0,
) -> bytes:
    params = build_wms_params(req)

    url = f"{GIBS_WMS_EPSG4326_BEST}?{urlencode(params)}"
    http_req = Request(url, headers={"User-Agent": "global-background/0.1"})
    try:
        with urlopen(http_req, timeout=timeout_s) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read()
    except HTTPError as exc:
        raise RuntimeError(f"GIBS WMS HTTP error: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"GIBS WMS network error: {getattr(exc, 'reason', exc)}") from exc

    # When layer/date unavailable, GIBS sometimes returns an XML ServiceException.
    if b"ServiceException" in data[:2048] or "xml" in content_type:
        raise RuntimeError(f"GIBS WMS returned an error for layer={req.layer}, date={req.date}")

    if len(data) < 10_000:
        raise RuntimeError("GIBS returned unexpectedly small image payload")

    return data


def iter_recent_dates(max_days_back: int, today: dt.date | None = None) -> Iterable[dt.date]:
    if today is None:
        today = dt.date.today()
    for i in range(0, max_days_back + 1):
        yield today - dt.timedelta(days=i)
