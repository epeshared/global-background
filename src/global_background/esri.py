from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


ESRI_WORLD_IMAGERY_EXPORT = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
)


@dataclass(frozen=True)
class EsriExportRequest:
    bbox_latlon: tuple[float, float, float, float]  # (lat_min, lon_min, lat_max, lon_max)
    width: int
    height: int
    image_format: str  # "jpg" or "png"


def fetch_esri_world_imagery(req: EsriExportRequest, timeout_s: float = 30.0) -> bytes:
    lat_min, lon_min, lat_max, lon_max = req.bbox_latlon

    # ArcGIS export expects bbox in lon,lat order.
    bbox = f"{lon_min},{lat_min},{lon_max},{lat_max}"

    fmt = req.image_format.lower()
    if fmt in {"jpeg", "jpg"}:
        fmt = "jpg"
    elif fmt == "png":
        fmt = "png"
    else:
        raise ValueError(f"Unsupported image format: {req.image_format}")

    params = {
        "bbox": bbox,
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{req.width},{req.height}",
        "format": fmt,
        "f": "image",
    }

    url = f"{ESRI_WORLD_IMAGERY_EXPORT}?{urlencode(params)}"
    http_req = Request(url, headers={"User-Agent": "global-background/0.1"})

    try:
        with urlopen(http_req, timeout=timeout_s) as resp:
            data = resp.read()
    except HTTPError as exc:
        raise RuntimeError(f"ESRI export HTTP error: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"ESRI export network error: {getattr(exc, 'reason', exc)}") from exc

    if len(data) < 10_000:
        raise RuntimeError("ESRI returned unexpectedly small image payload")

    return data


def default_label() -> str:
    return "ESRI_World_Imagery"


def default_date() -> dt.date:
    # This source is not strictly daily; we still label with current day for metadata.
    return dt.date.today()
