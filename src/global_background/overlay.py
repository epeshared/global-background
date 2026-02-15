from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont  # type: ignore


@dataclass(frozen=True)
class OverlaySpec:
    text: str
    position: str
    margin_px: int
    font_size_px: int
    fill_rgba: tuple[int, int, int, int]
    stroke_rgba: tuple[int, int, int, int]
    stroke_width_px: int


def _pick_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # Use default bitmap font as fallback; FreeType may not be available everywhere.
    try:
        return ImageFont.truetype("segoeui.ttf", size_px)
    except Exception:
        return ImageFont.load_default()


def apply_overlay(img: Image.Image, spec: OverlaySpec) -> Image.Image:
    if img.mode != "RGBA":
        base = img.convert("RGBA")
    else:
        base = img.copy()

    draw = ImageDraw.Draw(base)
    font = _pick_font(spec.font_size_px)

    # Measure text
    bbox = draw.textbbox((0, 0), spec.text, font=font, stroke_width=spec.stroke_width_px)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    margin = spec.margin_px
    if spec.position == "bottom-right":
        x = base.width - margin - text_w
        y = base.height - margin - text_h
    elif spec.position == "bottom-left":
        x = margin
        y = base.height - margin - text_h
    elif spec.position == "top-right":
        x = base.width - margin - text_w
        y = margin
    elif spec.position == "top-left":
        x = margin
        y = margin
    else:
        x = base.width - margin - text_w
        y = base.height - margin - text_h

    draw.text(
        (x, y),
        spec.text,
        font=font,
        fill=spec.fill_rgba,
        stroke_fill=spec.stroke_rgba,
        stroke_width=spec.stroke_width_px,
    )

    return base
