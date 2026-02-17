from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import tomllib


@dataclass(frozen=True)
class LocationConfig:
    name: str | None
    lat: float
    lon: float


@dataclass(frozen=True)
class AreaConfig:
    half_width_km: float
    half_height_km: float


@dataclass(frozen=True)
class ImageConfig:
    width: int
    height: int
    format: str
    quality: int


@dataclass(frozen=True)
class SatelliteConfig:
    provider: str  # "gibs" | "himawari" | "goes" (direct full-disk)
    layers: list[str]
    max_days_back: int
    himawari_band: str | None
    himawari_level_d: int
    himawari_product: str
    himawari_max_lookback_minutes: int
    himawari_layout: str  # "fill" (crop) | "fit" (contain/letterbox)

    # For full-disk providers (GOES/Himawari): additional scale factor applied in "fit" mode.
    # 1.0 = as large as possible while fitting; 0.75 = shrink by 25%.
    full_disk_scale: float

    # GOES (NOAA) full-disk (earth disc)
    goes_satellite: str
    goes_product: str
    goes_size: int


@dataclass(frozen=True)
class WallpaperConfig:
    style: str


@dataclass(frozen=True)
class OverlayConfig:
    enabled: bool
    text_template: str
    position: str
    margin_px: int
    font_size_px: int
    fill_rgba: tuple[int, int, int, int]
    stroke_rgba: tuple[int, int, int, int]
    stroke_width_px: int


@dataclass(frozen=True)
class RetentionConfig:
    keep_days: int


@dataclass(frozen=True)
class NetworkConfig:
    https_proxy: str | None
    http_proxy: str | None
    timeout_s: float


@dataclass(frozen=True)
class RegionConfig:
    # local: use a bbox around (lat, lon)
    # country: use the whole country's bbox (from config or best-effort resolver)
    # globe: render an earth "ball" centered at the chosen point
    mode: str  # "local" | "country" | "globe"
    country_bbox_latlon: tuple[float, float, float, float] | None
    country_name: str | None
    globe_center: str  # "country" | "location"
    globe_render_width: int | None
    globe_render_height: int | None
    globe_background_style: str  # "solid" | "gradient"
    globe_background_rgb: tuple[int, int, int]
    globe_background_rgb2: tuple[int, int, int]
    globe_background_stars: bool


@dataclass(frozen=True)
class AppConfig:
    update_interval_minutes: int
    output_dir: str
    retention: RetentionConfig
    network: NetworkConfig
    region: RegionConfig
    auto_location: bool
    location: LocationConfig
    area: AreaConfig
    image: ImageConfig
    satellite: SatelliteConfig
    wallpaper: WallpaperConfig
    overlay: OverlayConfig


def _require(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required config key: {key}")
    return mapping[key]


def _as_int(value: Any, key: str) -> int:
    try:
        return int(value)
    except Exception as exc:
        raise ValueError(f"Invalid int for {key}: {value!r}") from exc


def _as_int_or_auto(value: Any, key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"auto", "screen"}:
        return None
    v = _as_int(value, key)
    if v <= 0:
        return None
    return v


def _as_float(value: Any, key: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"Invalid float for {key}: {value!r}") from exc


def _as_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y"}:
            return True
        if v in {"false", "0", "no", "n"}:
            return False
    raise ValueError(f"Invalid bool for {key}: {value!r}")


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.example.toml to config.toml (recommended)"
        )

    suffix = path.suffix.lower()
    if suffix == ".toml":
        text = path.read_text(encoding="utf-8")
        # PowerShell's UTF8 encoding often writes a BOM; tomllib rejects it.
        if text.startswith("\ufeff"):
            text = text.lstrip("\ufeff")
        raw = tomllib.loads(text)
    elif suffix in {".json"}:
        text = path.read_text(encoding="utf-8")
        if text.startswith("\ufeff"):
            text = text.lstrip("\ufeff")
        raw = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "YAML config requires PyYAML. Either install extra deps: `python -m pip install -e .[full]` "
                "or switch to TOML config (config.example.toml)."
            ) from exc
        text = path.read_text(encoding="utf-8")
        if text.startswith("\ufeff"):
            text = text.lstrip("\ufeff")
        raw = yaml.safe_load(text)
    else:
        raise ValueError(f"Unsupported config format: {suffix}. Use .toml, .json, or .yaml/.yml")
    if not isinstance(raw, dict):
        raise ValueError("Config must be a YAML mapping")

    update_interval_minutes = _as_int(raw.get("update_interval_minutes", 30), "update_interval_minutes")
    output_dir = str(raw.get("output_dir", "out"))

    retention_raw = raw.get("retention") or {}
    if not isinstance(retention_raw, dict):
        raise ValueError("retention must be a mapping")
    keep_days = _as_int(retention_raw.get("keep_days", 1), "retention.keep_days")
    if keep_days < 1:
        raise ValueError("retention.keep_days must be >= 1")
    retention = RetentionConfig(keep_days=keep_days)

    net_raw = raw.get("network") or {}
    if not isinstance(net_raw, dict):
        raise ValueError("network must be a mapping")
    https_proxy = net_raw.get("https_proxy")
    http_proxy = net_raw.get("http_proxy")
    timeout_s = float(net_raw.get("timeout_s", 30))
    network = NetworkConfig(
        https_proxy=str(https_proxy) if https_proxy else None,
        http_proxy=str(http_proxy) if http_proxy else None,
        timeout_s=timeout_s,
    )

    region_raw = raw.get("region") or {}
    if not isinstance(region_raw, dict):
        raise ValueError("region must be a mapping")
    region_mode = str(region_raw.get("mode", "local")).strip().lower()
    if region_mode not in {"local", "country", "globe"}:
        raise ValueError("region.mode must be 'local', 'country', or 'globe'")

    bbox_val = region_raw.get("country_bbox_latlon")
    country_bbox: tuple[float, float, float, float] | None = None
    if bbox_val is not None:
        if isinstance(bbox_val, (list, tuple)) and len(bbox_val) == 4:
            country_bbox = (
                _as_float(bbox_val[0], "region.country_bbox_latlon[0]"),
                _as_float(bbox_val[1], "region.country_bbox_latlon[1]"),
                _as_float(bbox_val[2], "region.country_bbox_latlon[2]"),
                _as_float(bbox_val[3], "region.country_bbox_latlon[3]"),
            )
        else:
            raise ValueError("region.country_bbox_latlon must be [lat_min, lon_min, lat_max, lon_max]")

    globe_center = str(region_raw.get("globe_center", "country")).strip().lower()
    if globe_center not in {"country", "location"}:
        raise ValueError("region.globe_center must be 'country' or 'location'")

    globe_render_width = region_raw.get("globe_render_width")
    globe_render_height = region_raw.get("globe_render_height")
    grw = _as_int(globe_render_width, "region.globe_render_width") if globe_render_width else None
    grh = _as_int(globe_render_height, "region.globe_render_height") if globe_render_height else None
    if grw is not None and grw < 200:
        raise ValueError("region.globe_render_width must be >= 200")
    if grh is not None and grh < 200:
        raise ValueError("region.globe_render_height must be >= 200")

    bg_val = region_raw.get("globe_background_rgb", [0, 0, 0])
    if not (isinstance(bg_val, (list, tuple)) and len(bg_val) == 3):
        raise ValueError("region.globe_background_rgb must be [r,g,b]")
    globe_background_rgb = (int(bg_val[0]), int(bg_val[1]), int(bg_val[2]))

    bg_style = str(region_raw.get("globe_background_style", "solid")).strip().lower()
    if bg_style not in {"solid", "gradient"}:
        raise ValueError("region.globe_background_style must be 'solid' or 'gradient'")

    bg2_val = region_raw.get("globe_background_rgb2", [0, 0, 0])
    if not (isinstance(bg2_val, (list, tuple)) and len(bg2_val) == 3):
        raise ValueError("region.globe_background_rgb2 must be [r,g,b]")
    globe_background_rgb2 = (int(bg2_val[0]), int(bg2_val[1]), int(bg2_val[2]))

    globe_background_stars = _as_bool(region_raw.get("globe_background_stars", False), "region.globe_background_stars")

    region = RegionConfig(
        mode=region_mode,
        country_bbox_latlon=country_bbox,
        country_name=str(region_raw.get("country_name")) if region_raw.get("country_name") else None,
        globe_center=globe_center,
        globe_render_width=grw,
        globe_render_height=grh,
        globe_background_style=bg_style,
        globe_background_rgb=globe_background_rgb,
        globe_background_rgb2=globe_background_rgb2,
        globe_background_stars=globe_background_stars,
    )

    # NOTE: In TOML, any key placed after a table header like [retention] becomes
    # retention.auto_location instead of a top-level key. Accept that legacy layout.
    auto_location_val = raw.get("auto_location")
    if auto_location_val is None and "auto_location" in retention_raw:
        auto_location_val = retention_raw.get("auto_location")
    auto_location = _as_bool(auto_location_val if auto_location_val is not None else False, "auto_location")
    loc_raw = raw.get("location") or {}
    if not isinstance(loc_raw, dict):
        raise ValueError("location must be a mapping")

    location = LocationConfig(
        name=loc_raw.get("name"),
        lat=_as_float(loc_raw.get("lat", 0.0), "location.lat"),
        lon=_as_float(loc_raw.get("lon", 0.0), "location.lon"),
    )

    area_raw = raw.get("area") or {}
    if not isinstance(area_raw, dict):
        raise ValueError("area must be a mapping")

    area = AreaConfig(
        half_width_km=_as_float(area_raw.get("half_width_km", 250), "area.half_width_km"),
        half_height_km=_as_float(area_raw.get("half_height_km", 140), "area.half_height_km"),
    )

    image_raw = raw.get("image") or {}
    if not isinstance(image_raw, dict):
        raise ValueError("image must be a mapping")

    width_val = _as_int_or_auto(image_raw.get("width", 3840), "image.width")
    height_val = _as_int_or_auto(image_raw.get("height", 2160), "image.height")
    if width_val is None or height_val is None:
        try:
            from .screen import get_primary_screen_size

            sw, sh = get_primary_screen_size()
            width_val = int(sw)
            height_val = int(sh)
        except Exception:
            width_val = width_val or 1920
            height_val = height_val or 1080

    image = ImageConfig(
        width=int(width_val),
        height=int(height_val),
        format=str(image_raw.get("format", "jpg")).lower(),
        quality=_as_int(image_raw.get("quality", 92), "image.quality"),
    )

    sat_raw = raw.get("satellite") or {}
    if not isinstance(sat_raw, dict):
        raise ValueError("satellite must be a mapping")

    provider = str(sat_raw.get("provider", "gibs")).strip().lower()
    if provider not in {"gibs", "himawari", "goes"}:
        raise ValueError("satellite.provider must be 'gibs', 'himawari', or 'goes'")

    layers = sat_raw.get("layers")
    if layers is None:
        layers = ["VIIRS_SNPP_CorrectedReflectance_TrueColor"]
    if not isinstance(layers, list) or not all(isinstance(x, str) for x in layers):
        raise ValueError("satellite.layers must be a list of strings")

    band_raw = sat_raw.get("himawari_band", "B13")
    band = str(band_raw).strip() if band_raw is not None else ""
    if band == "" or band.lower() in {"none", "null"}:
        band = None

    satellite = SatelliteConfig(
        provider=provider,
        layers=[x.strip() for x in layers if x.strip()],
        max_days_back=_as_int(sat_raw.get("max_days_back", 10), "satellite.max_days_back"),
        himawari_band=band,
        himawari_level_d=_as_int(sat_raw.get("himawari_level_d", 8), "satellite.himawari_level_d"),
        himawari_product=str(sat_raw.get("himawari_product", "FULL_24h")).strip(),
        himawari_max_lookback_minutes=_as_int(
            sat_raw.get("himawari_max_lookback_minutes", 240),
            "satellite.himawari_max_lookback_minutes",
        ),
        himawari_layout=str(sat_raw.get("himawari_layout", "fill")).strip().lower(),
        full_disk_scale=_as_float(sat_raw.get("full_disk_scale", 1.0), "satellite.full_disk_scale"),
        goes_satellite=str(sat_raw.get("goes_satellite", "GOES18")).strip(),
        goes_product=str(sat_raw.get("goes_product", "GEOCOLOR")).strip(),
        goes_size=_as_int(sat_raw.get("goes_size", 5424), "satellite.goes_size"),
    )

    if satellite.himawari_layout not in {"fill", "fit"}:
        raise ValueError("satellite.himawari_layout must be 'fill' or 'fit'")

    if not (0.1 <= float(satellite.full_disk_scale) <= 2.0):
        raise ValueError("satellite.full_disk_scale must be between 0.1 and 2.0")

    # Backward-compatible mapping: himawari_size => himawari_level_d
    # size refers to final square resolution when using 550px tiles.
    # 550->1d, 1100->2d, 2200->4d, 4400->8d
    size_legacy = sat_raw.get("himawari_size")
    if size_legacy is not None:
        try:
            s = int(size_legacy)
            mapping = {550: 1, 1100: 2, 2200: 4, 4400: 8}
            if s in mapping:
                satellite = SatelliteConfig(
                    provider=satellite.provider,
                    layers=satellite.layers,
                    max_days_back=satellite.max_days_back,
                    himawari_band=satellite.himawari_band,
                    himawari_level_d=mapping[s],
                    himawari_product=satellite.himawari_product,
                    himawari_max_lookback_minutes=satellite.himawari_max_lookback_minutes,
                    himawari_layout=satellite.himawari_layout,
                    full_disk_scale=satellite.full_disk_scale,
                    goes_satellite=satellite.goes_satellite,
                    goes_product=satellite.goes_product,
                    goes_size=satellite.goes_size,
                )
        except Exception:
            pass

    wp_raw = raw.get("wallpaper") or {}
    if not isinstance(wp_raw, dict):
        raise ValueError("wallpaper must be a mapping")
    wallpaper = WallpaperConfig(style=str(wp_raw.get("style", "fill")).lower())

    ov_raw = raw.get("overlay") or {}
    if not isinstance(ov_raw, dict):
        raise ValueError("overlay must be a mapping")

    def _as_rgba(value: Any, key: str) -> tuple[int, int, int, int]:
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return tuple(int(x) for x in value)  # type: ignore[return-value]
        raise ValueError(f"{key} must be [r,g,b,a]")

    overlay = OverlayConfig(
        enabled=_as_bool(ov_raw.get("enabled", True), "overlay.enabled"),
        text_template=str(ov_raw.get("text_template", "{layer} {date}")),
        position=str(ov_raw.get("position", "bottom-right")),
        margin_px=_as_int(ov_raw.get("margin_px", 24), "overlay.margin_px"),
        font_size_px=_as_int(ov_raw.get("font_size_px", 28), "overlay.font_size_px"),
        fill_rgba=_as_rgba(ov_raw.get("fill_rgba", [255, 255, 255, 220]), "overlay.fill_rgba"),
        stroke_rgba=_as_rgba(ov_raw.get("stroke_rgba", [0, 0, 0, 180]), "overlay.stroke_rgba"),
        stroke_width_px=_as_int(ov_raw.get("stroke_width_px", 3), "overlay.stroke_width_px"),
    )

    return AppConfig(
        update_interval_minutes=update_interval_minutes,
        output_dir=output_dir,
        retention=retention,
        network=network,
        region=region,
        auto_location=auto_location,
        location=location,
        area=area,
        image=image,
        satellite=satellite,
        wallpaper=wallpaper,
        overlay=overlay,
    )
