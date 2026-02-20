from __future__ import annotations

import datetime as dt
import math
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from io import BytesIO

try:
    from PIL import Image, ImageFile  # type: ignore
    Image.MAX_IMAGE_PIXELS = 200_000_000  # allow FY-4B GCLR (~131M pixels)
    ImageFile.LOAD_TRUNCATED_IMAGES = True  # tolerate slightly truncated satellite JPEGs
except Exception:  # Pillow not installed
    Image = None  # type: ignore

from .config import AppConfig
from .country_bbox import resolve_country_bbox_latlon
from .globe import encode_image, make_background, render_orthographic_globe
from .himawari import HimawariFullDiskRequest, fetch_latest_full_disk_png
from .goes import GoesFullDiskRequest, fetch_latest_full_disk_jpg
from .slider import SliderFullDiskRequest, fetch_latest_full_disk_png as fetch_slider_latest_full_disk_png
from .fy4 import FY4FullDiskRequest, fetch_latest_full_disk_jpg as fetch_fy4_latest_full_disk_jpg
from .validate import validate_satellite_image, ImageValidationError
from .gibs import GibsRequest, fetch_wms_image_bytes, iter_recent_dates
from .esri import EsriExportRequest, default_date as esri_date, default_label as esri_label, fetch_esri_world_imagery
from .location import get_location_from_ip
try:
    from .overlay import OverlaySpec, apply_overlay
except Exception:
    OverlaySpec = None  # type: ignore
    apply_overlay = None  # type: ignore
from .wallpaper import set_wallpaper


@dataclass(frozen=True)
class FetchResult:
    layer: str
    date: dt.date
    image_bytes: bytes
    content_ext: str  # ".jpg" or ".png"


def _min_payload_bytes(width: int, height: int, ext: str) -> int:
    """Best-effort filter for placeholder/empty imagery.

    Some WMS responses return a syntactically valid image that's effectively blank (often
    compressing extremely small for large resolutions). We keep this heuristic intentionally
    lenient to avoid false negatives at smaller resolutions.
    """

    pixels = max(1, int(width) * int(height))
    ext = ext.lower()

    if ext in {".jpg", ".jpeg"}:
        # ~0.7% bytes-per-pixel with a small floor.
        return max(12_000, int(pixels * 0.007))
    if ext == ".png":
        # PNG often compresses less for photo content.
        return max(16_000, int(pixels * 0.012))

    return 12_000


def _km_to_deg_lat(km: float) -> float:
    return km / 111.0


def _km_to_deg_lon(km: float, lat_deg: float) -> float:
    return km / (111.0 * max(0.1, math.cos(math.radians(lat_deg))))


def _build_bbox(lat: float, lon: float, half_w_km: float, half_h_km: float) -> tuple[float, float, float, float]:
    dlat = _km_to_deg_lat(half_h_km)
    dlon = _km_to_deg_lon(half_w_km, lat)

    lat_min = max(-90.0, lat - dlat)
    lat_max = min(90.0, lat + dlat)

    lon_min = lon - dlon
    lon_max = lon + dlon
    if lon_min < -180.0:
        lon_min += 360.0
    if lon_max > 180.0:
        lon_max -= 360.0

    # Note: WMS bbox crossing antimeridian is tricky; keep width moderate to avoid wrap.
    if lon_min > lon_max:
        # fallback: clamp instead of wrap
        lon_min = -180.0
        lon_max = 180.0

    return (lat_min, lon_min, lat_max, lon_max)


def _nonblack_bbox_rgb(img, *, threshold: int = 10) -> tuple[int, int, int, int] | None:
    """Best-effort bounding box of non-black content.

    Used to center full-disk imagery content (earth disk) on screen in fit mode.
    Returns (left, top, right, bottom) in source pixel coordinates.
    """

    if Image is None:
        return None
    try:
        from PIL import ImageChops  # type: ignore

        rgb = img.convert("RGB")
        r, g, b = rgb.split()
        m = ImageChops.lighter(ImageChops.lighter(r, g), b)
        mask = m.point(lambda v: 255 if v > int(threshold) else 0)
        return mask.getbbox()
    except Exception:
        return None


def _replace_gray_band(img, *, gray_val: int = 128, tolerance: int = 12):
    """Replace solid gray (128,128,128) bands from JPEG truncation with black.

    Truncated JPEG decoding fills unprocessed regions with mid-gray.  This
    function detects contiguous rows of uniform gray at the bottom of the image
    (common with partially-downloaded satellite JPEGs) and replaces them with
    black so they blend into the space background.
    """
    if Image is None:
        return img
    try:
        from PIL import ImageDraw  # type: ignore

        w, h = img.size
        # Quick check: is the bottom-center pixel gray?
        r, g, b = img.getpixel((w // 2, h - 1))[:3]
        if not (abs(r - gray_val) <= tolerance and abs(g - gray_val) <= tolerance and abs(b - gray_val) <= tolerance):
            return img  # bottom is not gray — nothing to fix

        # Scan upward from bottom to find where the gray band starts.
        # Sample 5 columns to avoid false positives from a single gray pixel.
        sample_xs = [w // 6, w // 3, w // 2, 2 * w // 3, 5 * w // 6]
        gray_top = h  # will be set to the first non-gray row

        for y in range(h - 1, -1, -1):
            all_gray = True
            for sx in sample_xs:
                r, g, b = img.getpixel((sx, y))[:3]
                if not (abs(r - gray_val) <= tolerance and abs(g - gray_val) <= tolerance and abs(b - gray_val) <= tolerance):
                    all_gray = False
                    break
            if not all_gray:
                gray_top = y + 1
                break

        if gray_top >= h:
            return img  # entire image is gray (catastrophic) — return as-is

        gray_height = h - gray_top
        if gray_height < 4:
            return img  # negligible

        # Paint the gray band black
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, gray_top, w - 1, h - 1], fill=(0, 0, 0))

        print(
            f"[global-background] Replaced gray band (y={gray_top}..{h-1}, {gray_height}px) with black.",
            file=__import__("sys").stderr,
        )
        return img
    except Exception:
        return img


def _fit_paste_xy(
    *, target_w: int, target_h: int, src_w: int, src_h: int, scale: float, content_bbox: tuple[int, int, int, int] | None
) -> tuple[int, int]:
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))

    if content_bbox is None:
        return (int((target_w - new_w) // 2), int((target_h - new_h) // 2))

    l, t, r, b = content_bbox
    cx = (float(l) + float(r)) / 2.0
    cy = (float(t) + float(b)) / 2.0
    left = int(round((target_w / 2.0) - (cx * scale)))
    top = int(round((target_h / 2.0) - (cy * scale)))
    return (left, top)


def fetch_best_available(
    cfg: AppConfig,
    lat: float,
    lon: float,
    *,
    country_code: str | None = None,
    country_name: str | None = None,
) -> FetchResult:
    last_exc: Exception | None = None

    if cfg.satellite.provider == "fy4":
        if Image is None:
            print(
                "[global-background] Note: provider='fy4' returns a full-disk JPEG. "
                "Install Pillow to auto-crop/resize it to your screen (e.g. `python -m pip install -e .[full]`).",
                file=sys.stderr,
            )
        try:
            jpg, ts_utc, url = fetch_fy4_latest_full_disk_jpg(
                FY4FullDiskRequest(
                    satellite=cfg.satellite.fy4_satellite,
                    product=cfg.satellite.fy4_product,
                ),
                timeout_s=float(cfg.network.timeout_s),
            )

            sat = (cfg.satellite.fy4_satellite or "").strip().upper()
            prod = (cfg.satellite.fy4_product or "").strip().upper()
            label = f"FY4_{sat}_{prod}"

            # Validate downloaded image before processing
            vr = validate_satellite_image(jpg, is_jpeg=True, min_bytes=50_000)
            if not vr.valid:
                raise ImageValidationError(f"FY-4 image validation failed: {vr.reason}")

            if Image is not None:
                try:
                    img = Image.open(BytesIO(jpg)).convert("RGB")
                    img.load()

                    # Fix gray bands from truncated JPEG downloads
                    img = _replace_gray_band(img)

                    src_w, src_h = img.size
                    target_w, target_h = int(cfg.image.width), int(cfg.image.height)

                    layout = (cfg.satellite.himawari_layout or "fill").strip().lower()
                    if layout == "fit":
                        bg = make_background(
                            width=target_w,
                            height=target_h,
                            style=cfg.region.globe_background_style,
                            rgb1=cfg.region.globe_background_rgb,
                            rgb2=cfg.region.globe_background_rgb2,
                            stars=cfg.region.globe_background_stars,
                        )
                        scale = min(target_w / max(1, src_w), target_h / max(1, src_h))
                        scale *= float(getattr(cfg.satellite, "full_disk_scale", 1.0) or 1.0)
                        bbox = _nonblack_bbox_rgb(img)
                        new_w = max(1, int(round(src_w * scale)))
                        new_h = max(1, int(round(src_h * scale)))
                        fg = img.resize((new_w, new_h), resample=Image.LANCZOS)
                        left, top = _fit_paste_xy(
                            target_w=target_w,
                            target_h=target_h,
                            src_w=src_w,
                            src_h=src_h,
                            scale=scale,
                            content_bbox=bbox,
                        )
                        bg.paste(fg, (left, top))
                        img = bg
                    else:
                        target_aspect = target_w / max(1, target_h)
                        src_aspect = src_w / max(1, src_h)

                        if abs(src_aspect - target_aspect) > 1e-6:
                            if target_aspect > src_aspect:
                                crop_h = int(round(src_w / target_aspect))
                                crop_h = max(1, min(src_h, crop_h))
                                top = (src_h - crop_h) // 2
                                img = img.crop((0, top, src_w, top + crop_h))
                            else:
                                crop_w = int(round(src_h * target_aspect))
                                crop_w = max(1, min(src_w, crop_w))
                                left = (src_w - crop_w) // 2
                                img = img.crop((left, 0, left + crop_w, src_h))

                        img = img.resize((target_w, target_h), resample=Image.LANCZOS)

                    buf = BytesIO()
                    if cfg.image.format in {"jpg", "jpeg"}:
                        img.save(buf, format="JPEG", quality=cfg.image.quality, optimize=True)
                        return FetchResult(layer=label, date=ts_utc.date(), image_bytes=buf.getvalue(), content_ext=".jpg")
                    img.save(buf, format="PNG", optimize=True)
                    return FetchResult(layer=label, date=ts_utc.date(), image_bytes=buf.getvalue(), content_ext=".png")
                except Exception as img_exc:
                    print(
                        f"[global-background] FY-4 image transform failed, returning raw image. "
                        f"Reason: {img_exc!r}",
                        file=sys.stderr,
                    )

            return FetchResult(layer=label, date=ts_utc.date(), image_bytes=jpg, content_ext=".jpg")
        except ImageValidationError:
            raise  # Don't fall back — let caller retry
        except Exception as exc:
            last_exc = exc
            print(
                "[global-background] FY-4 fetch failed; falling back to SLIDER/GOES/Himawari/GIBS/ESRI. "
                f"Reason: {exc!r}",
                file=sys.stderr,
            )

    if cfg.satellite.provider == "slider":
        if Image is None:
            print(
                "[global-background] Note: provider='slider' returns a square full-disk image. "
                "Install Pillow to stitch tiles and to auto-crop/resize it to your screen (e.g. `python -m pip install -e .[full]`).",
                file=sys.stderr,
            )
        try:
            png, ts_utc, url = fetch_slider_latest_full_disk_png(
                SliderFullDiskRequest(
                    satellite=cfg.satellite.slider_satellite,
                    sector=cfg.satellite.slider_sector,
                    product=cfg.satellite.slider_product,
                    max_level=int(cfg.satellite.slider_max_level),
                ),
                timeout_s=float(cfg.network.timeout_s),
                target_max_dim_px=max(int(cfg.image.width), int(cfg.image.height)),
            )

            sat = (cfg.satellite.slider_satellite or "").strip().upper()
            sector = (cfg.satellite.slider_sector or "").strip().upper()
            product = (cfg.satellite.slider_product or "").strip().upper()
            label = f"SLIDER_{sat}_{sector}_{product}"
            _ = url  # kept for potential logging later

            # If Pillow is available, transform the square full-disk image into the configured
            # wallpaper size.
            if Image is not None:
                try:
                    img = Image.open(BytesIO(png)).convert("RGB")
                    img.load()

                    src_w, src_h = img.size
                    target_w, target_h = int(cfg.image.width), int(cfg.image.height)

                    layout = (cfg.satellite.himawari_layout or "fill").strip().lower()
                    if layout == "fit":
                        bg = make_background(
                            width=target_w,
                            height=target_h,
                            style=cfg.region.globe_background_style,
                            rgb1=cfg.region.globe_background_rgb,
                            rgb2=cfg.region.globe_background_rgb2,
                            stars=cfg.region.globe_background_stars,
                        )
                        scale = min(target_w / max(1, src_w), target_h / max(1, src_h))
                        scale *= float(getattr(cfg.satellite, "full_disk_scale", 1.0) or 1.0)
                        bbox = _nonblack_bbox_rgb(img)
                        new_w = max(1, int(round(src_w * scale)))
                        new_h = max(1, int(round(src_h * scale)))
                        fg = img.resize((new_w, new_h), resample=Image.LANCZOS)
                        left, top = _fit_paste_xy(
                            target_w=target_w,
                            target_h=target_h,
                            src_w=src_w,
                            src_h=src_h,
                            scale=scale,
                            content_bbox=bbox,
                        )
                        bg.paste(fg, (left, top))
                        img = bg
                    else:
                        target_aspect = target_w / max(1, target_h)
                        src_aspect = src_w / max(1, src_h)

                        if abs(src_aspect - target_aspect) > 1e-6:
                            if target_aspect > src_aspect:
                                crop_h = int(round(src_w / target_aspect))
                                crop_h = max(1, min(src_h, crop_h))
                                top = (src_h - crop_h) // 2
                                img = img.crop((0, top, src_w, top + crop_h))
                            else:
                                crop_w = int(round(src_h * target_aspect))
                                crop_w = max(1, min(src_w, crop_w))
                                left = (src_w - crop_w) // 2
                                img = img.crop((left, 0, left + crop_w, src_h))

                        img = img.resize((target_w, target_h), resample=Image.LANCZOS)

                    buf = BytesIO()
                    if cfg.image.format in {"jpg", "jpeg"}:
                        img.save(buf, format="JPEG", quality=cfg.image.quality, optimize=True)
                        return FetchResult(layer=label, date=ts_utc.date(), image_bytes=buf.getvalue(), content_ext=".jpg")
                    img.save(buf, format="PNG", optimize=True)
                    return FetchResult(layer=label, date=ts_utc.date(), image_bytes=buf.getvalue(), content_ext=".png")
                except Exception as img_exc:
                    print(
                        f"[global-background] SLIDER image transform failed, returning raw image. "
                        f"Reason: {img_exc!r}",
                        file=sys.stderr,
                    )

            return FetchResult(layer=label, date=ts_utc.date(), image_bytes=png, content_ext=".png")
        except Exception as exc:
            last_exc = exc
            print(
                "[global-background] SLIDER fetch failed; falling back to GOES/Himawari/GIBS/ESRI. "
                f"Reason: {exc!r}",
                file=sys.stderr,
            )

    if cfg.satellite.provider == "goes":
        if Image is None:
            print(
                "[global-background] Note: provider='goes' returns a square full-disk image. "
                "Install Pillow to auto-crop/resize it to your screen (e.g. `python -m pip install -e .[full]`).",
                file=sys.stderr,
            )
        try:
            jpg, ts_utc, url = fetch_latest_full_disk_jpg(
                GoesFullDiskRequest(
                    satellite=cfg.satellite.goes_satellite,
                    product=cfg.satellite.goes_product,
                    size=int(cfg.satellite.goes_size),
                ),
                timeout_s=float(cfg.network.timeout_s),
            )

            sat = (cfg.satellite.goes_satellite or "").strip().upper() or "GOES18"
            product = (cfg.satellite.goes_product or "").strip().upper() or "GEOCOLOR"
            label = f"GOES_{sat}_{product}_{int(cfg.satellite.goes_size)}"
            _ = url  # kept for potential logging later

            # If Pillow is available, transform the square full-disk image into the configured
            # wallpaper size.
            if Image is not None:
                try:
                    img = Image.open(BytesIO(jpg)).convert("RGB")
                    img.load()

                    src_w, src_h = img.size
                    target_w, target_h = int(cfg.image.width), int(cfg.image.height)

                    layout = (cfg.satellite.himawari_layout or "fill").strip().lower()
                    if layout == "fit":
                        bg = make_background(
                            width=target_w,
                            height=target_h,
                            style=cfg.region.globe_background_style,
                            rgb1=cfg.region.globe_background_rgb,
                            rgb2=cfg.region.globe_background_rgb2,
                            stars=cfg.region.globe_background_stars,
                        )
                        scale = min(target_w / max(1, src_w), target_h / max(1, src_h))
                        scale *= float(getattr(cfg.satellite, "full_disk_scale", 1.0) or 1.0)
                        bbox = _nonblack_bbox_rgb(img)
                        new_w = max(1, int(round(src_w * scale)))
                        new_h = max(1, int(round(src_h * scale)))
                        fg = img.resize((new_w, new_h), resample=Image.LANCZOS)
                        left, top = _fit_paste_xy(
                            target_w=target_w,
                            target_h=target_h,
                            src_w=src_w,
                            src_h=src_h,
                            scale=scale,
                            content_bbox=bbox,
                        )
                        bg.paste(fg, (left, top))
                        img = bg
                    else:
                        target_aspect = target_w / max(1, target_h)
                        src_aspect = src_w / max(1, src_h)

                        if abs(src_aspect - target_aspect) > 1e-6:
                            if target_aspect > src_aspect:
                                crop_h = int(round(src_w / target_aspect))
                                crop_h = max(1, min(src_h, crop_h))
                                top = (src_h - crop_h) // 2
                                img = img.crop((0, top, src_w, top + crop_h))
                            else:
                                crop_w = int(round(src_h * target_aspect))
                                crop_w = max(1, min(src_w, crop_w))
                                left = (src_w - crop_w) // 2
                                img = img.crop((left, 0, left + crop_w, src_h))

                        img = img.resize((target_w, target_h), resample=Image.LANCZOS)

                    buf = BytesIO()
                    if cfg.image.format in {"jpg", "jpeg"}:
                        img.save(buf, format="JPEG", quality=cfg.image.quality, optimize=True)
                        return FetchResult(layer=label, date=ts_utc.date(), image_bytes=buf.getvalue(), content_ext=".jpg")
                    img.save(buf, format="PNG", optimize=True)
                    return FetchResult(layer=label, date=ts_utc.date(), image_bytes=buf.getvalue(), content_ext=".png")
                except Exception as img_exc:
                    print(
                        f"[global-background] Himawari image transform failed, returning raw image. "
                        f"Reason: {img_exc!r}",
                        file=sys.stderr,
                    )

            # No Pillow: keep the original JPG.
            return FetchResult(layer=label, date=ts_utc.date(), image_bytes=jpg, content_ext=".jpg")
        except Exception as exc:
            last_exc = exc
            print(
                "[global-background] GOES fetch failed; falling back to Himawari/GIBS/ESRI. "
                f"Reason: {exc!r}",
                file=sys.stderr,
            )

    if cfg.satellite.provider == "himawari":
        if Image is None:
            print(
                "[global-background] Note: provider='himawari' returns a square full-disk image. "
                "Install Pillow to auto-crop/resize it to your screen (e.g. `python -m pip install -e .[full]`).",
                file=sys.stderr,
            )
        try:
            # Direct full-disk download; ignores region/local bbox.
            png, ts_utc, url = fetch_latest_full_disk_png(
                HimawariFullDiskRequest(
                    product=cfg.satellite.himawari_product,
                    band=cfg.satellite.himawari_band,
                    level_d=int(cfg.satellite.himawari_level_d),
                ),
                timeout_s=float(cfg.network.timeout_s),
                max_lookback_minutes=int(cfg.satellite.himawari_max_lookback_minutes),
            )
            # label by UTC timestamp
            band = (cfg.satellite.himawari_band or "").strip()
            if band:
                label = f"HIMAWARI_{cfg.satellite.himawari_product}_{band}_{cfg.satellite.himawari_level_d}d"
            else:
                label = f"HIMAWARI_{cfg.satellite.himawari_product}_{cfg.satellite.himawari_level_d}d"
            _ = url  # kept for potential logging later

            # If Pillow is available, transform the square full-disk image into the configured
            # wallpaper size.
            if Image is not None:
                try:
                    img = Image.open(BytesIO(png)).convert("RGB")
                    img.load()

                    src_w, src_h = img.size
                    target_w, target_h = int(cfg.image.width), int(cfg.image.height)

                    layout = (cfg.satellite.himawari_layout or "fill").strip().lower()
                    if layout == "fit":
                        # Keep the full disk visible: scale-to-fit + letterbox with space background.
                        bg = make_background(
                            width=target_w,
                            height=target_h,
                            style=cfg.region.globe_background_style,
                            rgb1=cfg.region.globe_background_rgb,
                            rgb2=cfg.region.globe_background_rgb2,
                            stars=cfg.region.globe_background_stars,
                        )
                        scale = min(target_w / max(1, src_w), target_h / max(1, src_h))
                        scale *= float(getattr(cfg.satellite, "full_disk_scale", 1.0) or 1.0)
                        bbox = _nonblack_bbox_rgb(img)
                        new_w = max(1, int(round(src_w * scale)))
                        new_h = max(1, int(round(src_h * scale)))
                        fg = img.resize((new_w, new_h), resample=Image.LANCZOS)
                        left, top = _fit_paste_xy(
                            target_w=target_w,
                            target_h=target_h,
                            src_w=src_w,
                            src_h=src_h,
                            scale=scale,
                            content_bbox=bbox,
                        )
                        bg.paste(fg, (left, top))
                        img = bg
                    else:
                        # Fill the wallpaper: center-crop to aspect then resize.
                        target_aspect = target_w / max(1, target_h)
                        src_aspect = src_w / max(1, src_h)

                        if abs(src_aspect - target_aspect) > 1e-6:
                            if target_aspect > src_aspect:
                                # Need a wider crop: reduce height.
                                crop_h = int(round(src_w / target_aspect))
                                crop_h = max(1, min(src_h, crop_h))
                                top = (src_h - crop_h) // 2
                                img = img.crop((0, top, src_w, top + crop_h))
                            else:
                                # Need a taller/narrower crop: reduce width.
                                crop_w = int(round(src_h * target_aspect))
                                crop_w = max(1, min(src_w, crop_w))
                                left = (src_w - crop_w) // 2
                                img = img.crop((left, 0, left + crop_w, src_h))

                        img = img.resize((target_w, target_h), resample=Image.LANCZOS)

                    buf = BytesIO()
                    if cfg.image.format in {"jpg", "jpeg"}:
                        img.save(buf, format="JPEG", quality=cfg.image.quality, optimize=True)
                        return FetchResult(
                            layer=label, date=ts_utc.date(), image_bytes=buf.getvalue(), content_ext=".jpg"
                        )
                    else:
                        img.save(buf, format="PNG", optimize=True)
                        return FetchResult(
                            layer=label, date=ts_utc.date(), image_bytes=buf.getvalue(), content_ext=".png"
                        )
                except Exception as img_exc:
                    print(
                        f"[global-background] GOES image transform failed, returning raw image. "
                        f"Reason: {img_exc!r}",
                        file=sys.stderr,
                    )

            # Fallback: return the original payload as PNG.
            return FetchResult(layer=label, date=ts_utc.date(), image_bytes=png, content_ext=".png")
        except Exception as exc:
            last_exc = exc
            print(
                "[global-background] Himawari fetch failed; falling back to GIBS/ESRI. "
                f"Reason: {exc!r}",
                file=sys.stderr,
            )

    if cfg.region.mode == "globe":
        # Always fetch a global equirectangular map as the source for globe rendering.
        bbox = (-90.0, -180.0, 90.0, 180.0)
    elif cfg.region.mode == "country":
        bbox = cfg.region.country_bbox_latlon
        if bbox is None:
            bbox = resolve_country_bbox_latlon(
                country_code=country_code,
                country_name=cfg.region.country_name or country_name,
                timeout_s=float(cfg.network.timeout_s),
            )
    else:
        bbox = _build_bbox(lat, lon, cfg.area.half_width_km, cfg.area.half_height_km)
    for layer in cfg.satellite.layers:
        for date in iter_recent_dates(cfg.satellite.max_days_back):
            try:
                req = GibsRequest(
                    layer=layer,
                    date=date,
                    bbox_latlon=bbox,
                    width=cfg.image.width,
                    height=cfg.image.height,
                    image_format=cfg.image.format,
                )
                ext = ".jpg" if cfg.image.format in {"jpg", "jpeg"} else ".png"
                data = fetch_wms_image_bytes(req, timeout_s=cfg.network.timeout_s)
                if len(data) < _min_payload_bytes(cfg.image.width, cfg.image.height, ext):
                    raise RuntimeError(
                        f"Suspiciously small payload ({len(data)} bytes) for {cfg.image.width}x{cfg.image.height}{ext}"
                    )
                return FetchResult(layer=layer, date=date, image_bytes=data, content_ext=ext)
            except Exception as exc:
                last_exc = exc
                continue

    # Fallback: ESRI World Imagery (not truly "real-time", but often accessible in enterprise networks)
    try:
        data = fetch_esri_world_imagery(
            EsriExportRequest(
                bbox_latlon=bbox,
                width=cfg.image.width,
                height=cfg.image.height,
                image_format=cfg.image.format,
            ),
            timeout_s=cfg.network.timeout_s,
        )
        ext = ".jpg" if cfg.image.format in {"jpg", "jpeg"} else ".png"
        if len(data) < _min_payload_bytes(cfg.image.width, cfg.image.height, ext):
            raise RuntimeError(
                f"Suspiciously small payload ({len(data)} bytes) for {cfg.image.width}x{cfg.image.height}{ext}"
            )
        return FetchResult(layer=esri_label(), date=esri_date(), image_bytes=data, content_ext=ext)
    except Exception as exc:
        last_exc = exc

    raise RuntimeError(f"Unable to fetch any imagery (last error: {last_exc!r})")


def _save_outputs(cfg: AppConfig, result: FetchResult, lat: float, lon: float) -> tuple[Path, Path | None]:
    out_root = Path(cfg.output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    # Store by local run date so the folder itself is the time-series bucket.
    # Folder name is ISO date, so lexicographic order == chronological order.
    day_dir = out_root / dt.date.today().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    stamp = dt.datetime.now().strftime("%H%M%S")
    base = day_dir / f"{dt.date.today().strftime('%Y%m%d')}_{stamp}_{result.layer}_{result.date.isoformat()}"

    # Save original payload as-is (no dependency on Pillow)
    image_path = base.with_suffix(result.content_ext)
    image_path.write_bytes(result.image_bytes)

    bmp_path: Path | None = None
    if Image is not None:
        # If Pillow is available, optionally create BMP for max compatibility.
        try:
            img = Image.open(BytesIO(result.image_bytes))
            img.load()
            bmp_path = base.with_suffix(".bmp")
            img.convert("RGB").save(bmp_path, format="BMP")
        except Exception:
            bmp_path = None

    meta_path = base.with_suffix(".txt")
    meta_path.write_text(
        "\n".join(
            [
                f"layer={result.layer}",
                f"date={result.date.isoformat()}",
                f"lat={lat}",
                f"lon={lon}",
                f"bbox_half_width_km={cfg.area.half_width_km}",
                f"bbox_half_height_km={cfg.area.half_height_km}",
                f"size={cfg.image.width}x{cfg.image.height}",
            ]
        ),
        encoding="utf-8",
    )

    return image_path, bmp_path


def cleanup_old_days(output_dir: Path, keep_days: int) -> None:
    output_dir = output_dir.expanduser().resolve()
    if not output_dir.exists():
        return

    cutoff = dt.date.today() - dt.timedelta(days=keep_days - 1)

    for child in output_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            folder_date = dt.date.fromisoformat(child.name)
        except Exception:
            continue
        if folder_date < cutoff:
            shutil.rmtree(child, ignore_errors=True)


def run_once(cfg: AppConfig, dry_run: bool = False) -> None:
    # Apply proxy settings for urllib-based fetches.
    # Priority: config.toml -> existing environment variables -> Windows system proxy (best-effort).
    if cfg.network.https_proxy:
        os.environ["HTTPS_PROXY"] = cfg.network.https_proxy
        os.environ["https_proxy"] = cfg.network.https_proxy
    if cfg.network.http_proxy:
        os.environ["HTTP_PROXY"] = cfg.network.http_proxy
        os.environ["http_proxy"] = cfg.network.http_proxy

    if (
        not cfg.network.http_proxy
        and not cfg.network.https_proxy
        and not os.environ.get("HTTP_PROXY")
        and not os.environ.get("HTTPS_PROXY")
        and not os.environ.get("http_proxy")
        and not os.environ.get("https_proxy")
        and sys.platform.startswith("win")
    ):
        try:
            from .winproxy import get_windows_proxy_settings

            s = get_windows_proxy_settings()
            if s is not None:
                if s.http_proxy:
                    os.environ["HTTP_PROXY"] = s.http_proxy
                    os.environ["http_proxy"] = s.http_proxy
                if s.https_proxy:
                    os.environ["HTTPS_PROXY"] = s.https_proxy
                    os.environ["https_proxy"] = s.https_proxy
        except Exception:
            pass

    geo = None
    if cfg.auto_location:
        try:
            geo = get_location_from_ip(timeout_s=float(cfg.network.timeout_s))
        except Exception as exc:
            geo = None
            print(
                "[global-background] auto_location failed; falling back to configured location. "
                f"Reason: {exc!r}",
                file=sys.stderr,
            )

    if geo is not None:
        lat, lon = geo.lat, geo.lon
        place_name = geo.name or cfg.location.name
        cc = getattr(geo, "country_code", None)
        cn = getattr(geo, "country_name", None)
    else:
        lat, lon = cfg.location.lat, cfg.location.lon
        place_name = cfg.location.name
        cc = None
        cn = None

    # Globe mode: fetch a global map at a smaller render size, project, then upscale to target.
    if cfg.region.mode == "globe":
        if Image is None:
            raise RuntimeError("region.mode='globe' requires Pillow. Install extras: python -m pip install -e .[full]")

        # Choose globe center
        center_lat, center_lon = lat, lon
        if cfg.region.globe_center == "country":
            try:
                bbox = cfg.region.country_bbox_latlon
                if bbox is None:
                    bbox = resolve_country_bbox_latlon(
                        country_code=cc,
                        country_name=cfg.region.country_name or cn,
                        timeout_s=float(cfg.network.timeout_s),
                    )
                lat_min, lon_min, lat_max, lon_max = bbox
                center_lat = (lat_min + lat_max) * 0.5
                center_lon = (lon_min + lon_max) * 0.5
            except Exception:
                center_lat, center_lon = lat, lon

        # Render size (fast), then upscale (quality)
        render_w = cfg.region.globe_render_width or min(cfg.image.width, 1920)
        render_h = cfg.region.globe_render_height or min(cfg.image.height, 1080)

        # Fetch global source at ~2x render size for decent detail
        src_w = max(1024, int(render_w * 2))
        src_h = max(512, int(render_h * 2))

        # Use global bbox
        global_bbox = (-90.0, -180.0, 90.0, 180.0)

        # Fetch best layer/date with the source size
        last_exc: Exception | None = None
        for layer in cfg.satellite.layers:
            for date in iter_recent_dates(cfg.satellite.max_days_back):
                try:
                    req = GibsRequest(
                        layer=layer,
                        date=date,
                        bbox_latlon=global_bbox,
                        width=src_w,
                        height=src_h,
                        image_format=cfg.image.format,
                    )
                    ext = ".jpg" if cfg.image.format in {"jpg", "jpeg"} else ".png"
                    data = fetch_wms_image_bytes(req, timeout_s=cfg.network.timeout_s)
                    if len(data) < _min_payload_bytes(src_w, src_h, ext):
                        raise RuntimeError(
                            f"Suspiciously small payload ({len(data)} bytes) for {src_w}x{src_h}{ext}"
                        )

                    globe_small = render_orthographic_globe(
                        source_image_bytes=data,
                        center_lat=center_lat,
                        center_lon=center_lon,
                        out_width=render_w,
                        out_height=render_h,
                        background_style=cfg.region.globe_background_style,
                        background_rgb=cfg.region.globe_background_rgb,
                        background_rgb2=cfg.region.globe_background_rgb2,
                        background_stars=cfg.region.globe_background_stars,
                    )
                    # Upscale to target size (C-optimized)
                    globe_final = globe_small.resize((cfg.image.width, cfg.image.height), resample=Image.LANCZOS)
                    out_bytes = encode_image(globe_final, cfg.image.format, cfg.image.quality)
                    result = FetchResult(layer=f"GLOBE_{layer}", date=date, image_bytes=out_bytes, content_ext=ext)
                    break
                except Exception as exc:
                    last_exc = exc
                    continue
            else:
                continue
            break
        else:
            raise RuntimeError(f"Unable to fetch globe imagery (last error: {last_exc!r})")
    else:
        result = fetch_best_available(
            cfg,
            lat,
            lon,
            country_code=cc,
            country_name=cn,
        )

    # Optional overlay requires Pillow. For PNG from Himawari, we also need Pillow.
    if cfg.overlay.enabled and Image is not None and apply_overlay is not None and OverlaySpec is not None:
        try:
            img = Image.open(BytesIO(result.image_bytes))
            img.load()
            text = cfg.overlay.text_template.format(
                layer=result.layer,
                date=result.date.isoformat(),
                lat=lat,
                lon=lon,
                name=place_name or "",
            )
            img2 = apply_overlay(
                img,
                OverlaySpec(
                    text=text,
                    position=cfg.overlay.position,
                    margin_px=cfg.overlay.margin_px,
                    font_size_px=cfg.overlay.font_size_px,
                    fill_rgba=cfg.overlay.fill_rgba,
                    stroke_rgba=cfg.overlay.stroke_rgba,
                    stroke_width_px=cfg.overlay.stroke_width_px,
                ),
            )
            # Re-encode after overlay
            buf = BytesIO()
            if cfg.image.format in {"jpg", "jpeg"}:
                img2.convert("RGB").save(buf, format="JPEG", quality=cfg.image.quality, optimize=True)
                updated = FetchResult(result.layer, result.date, buf.getvalue(), ".jpg")
            else:
                img2.convert("RGBA").save(buf, format="PNG", optimize=True)
                updated = FetchResult(result.layer, result.date, buf.getvalue(), ".png")
            result = updated
        except Exception:
            pass

    # If user requested JPG output but provider returned PNG (Himawari), convert when Pillow is available.
    if result.content_ext == ".png" and cfg.image.format in {"jpg", "jpeg"} and Image is not None:
        try:
            img = Image.open(BytesIO(result.image_bytes))
            img.load()
            buf = BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=cfg.image.quality, optimize=True)
            result = FetchResult(result.layer, result.date, buf.getvalue(), ".jpg")
        except Exception:
            pass

    image_path, bmp_path = _save_outputs(cfg, result, lat, lon)

    # Retention: keep only the most recent N days of day-folders.
    cleanup_old_days(Path(cfg.output_dir), cfg.retention.keep_days)

    if dry_run:
        return

    # Prefer BMP for compatibility when available.
    set_wallpaper((bmp_path or image_path), style=cfg.wallpaper.style)
