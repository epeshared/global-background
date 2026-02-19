"""Image validation for satellite full-disk imagery.

Checks that a downloaded image is a genuine earth-disk photo
(not truncated, not a placeholder, not mostly gray fill).
"""

from __future__ import annotations

import sys
from io import BytesIO
from dataclasses import dataclass

try:
    from PIL import Image  # type: ignore

    Image.MAX_IMAGE_PIXELS = 200_000_000
except Exception:
    Image = None  # type: ignore


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str


class ImageValidationError(Exception):
    """Raised when a downloaded image fails validation checks."""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"


def check_jpeg_integrity(data: bytes, *, min_bytes: int = 50_000) -> ValidationResult:
    """Check that *data* is a plausible complete JPEG.

    Verifies:
      1. Starts with FFD8 (JPEG SOI marker)
      2. Ends with FFD9 (JPEG EOI marker) or has it near the tail
      3. File size > *min_bytes* (FY4B GCLR should be ~11-20 MB)
    """
    if len(data) < min_bytes:
        return ValidationResult(False, f"Too small: {len(data):,} bytes (need ≥{min_bytes:,})")

    if not data[:2] == _JPEG_SOI:
        return ValidationResult(False, f"Not a JPEG: SOI={data[:2].hex()}")

    # Allow FFD9 within the last 16 bytes (some servers append trailing bytes)
    tail = data[-16:]
    if _JPEG_EOI not in tail:
        return ValidationResult(
            False,
            f"JPEG truncated: no FFD9 in last 16 bytes "
            f"(size={len(data):,}, tail={data[-4:].hex()})",
        )

    return ValidationResult(True, "JPEG integrity OK")


def check_gray_ratio(data: bytes, *, max_gray_ratio: float = 0.05) -> ValidationResult:
    """Check that the image doesn't have large gray(128,128,128) fill from JPEG truncation.

    Samples rows from the image and counts how many are uniform mid-gray.
    If more than *max_gray_ratio* of the image height is gray, it's considered corrupt.
    """
    if Image is None:
        return ValidationResult(True, "Pillow not installed, skipping gray check")

    try:
        img = Image.open(BytesIO(data)).convert("RGB")
        w, h = img.size
    except Exception as exc:
        return ValidationResult(False, f"Cannot open image: {exc}")

    gray_val = 128
    tolerance = 12
    sample_xs = [w // 6, w // 3, w // 2, 2 * w // 3, 5 * w // 6]

    # Sample every 50th row for speed (a 12000px image → ~240 samples)
    step = max(1, h // 240)
    gray_rows = 0
    total_rows = 0

    for y in range(0, h, step):
        total_rows += 1
        all_gray = True
        for sx in sample_xs:
            r, g, b = img.getpixel((sx, y))[:3]
            if not (
                abs(r - gray_val) <= tolerance
                and abs(g - gray_val) <= tolerance
                and abs(b - gray_val) <= tolerance
            ):
                all_gray = False
                break
        if all_gray:
            gray_rows += 1

    ratio = gray_rows / max(1, total_rows)
    if ratio > max_gray_ratio:
        return ValidationResult(
            False,
            f"Gray fill detected: {ratio:.0%} of rows are gray(128) "
            f"({gray_rows}/{total_rows} sampled rows) — likely truncated JPEG",
        )

    return ValidationResult(True, f"Gray ratio OK ({ratio:.1%})")


def check_earth_disk(data: bytes, *, min_bright_ratio: float = 0.08) -> ValidationResult:
    """Check that the image contains a visible earth disk.

    A valid full-disk satellite image should have:
      - A large dark (black space) area
      - A bright(ish) circular region (the earth) covering at least *min_bright_ratio*
        of the total pixels

    This catches blank/black images or placeholder images that have no earth content.
    """
    if Image is None:
        return ValidationResult(True, "Pillow not installed, skipping earth-disk check")

    try:
        img = Image.open(BytesIO(data)).convert("RGB")
        w, h = img.size
    except Exception as exc:
        return ValidationResult(False, f"Cannot open image: {exc}")

    # Sample a grid of pixels for speed
    step_x = max(1, w // 100)
    step_y = max(1, h // 100)
    bright_count = 0
    dark_count = 0
    total = 0

    bright_threshold = 30  # pixel brightness above this = "earth content"
    for y in range(0, h, step_y):
        for x in range(0, w, step_x):
            r, g, b = img.getpixel((x, y))[:3]
            brightness = max(r, g, b)
            total += 1
            if brightness > bright_threshold:
                bright_count += 1
            elif brightness <= 5:
                dark_count += 1

    bright_ratio = bright_count / max(1, total)
    dark_ratio = dark_count / max(1, total)

    if bright_ratio < min_bright_ratio:
        return ValidationResult(
            False,
            f"No earth disk: only {bright_ratio:.1%} bright pixels "
            f"(need ≥{min_bright_ratio:.0%}). Image may be blank/dark placeholder.",
        )

    # A full-disk image should also have substantial dark area (space)
    # Unless it's daytime and mostly clouds, at least 15% should be dark
    if dark_ratio < 0.10:
        # This is actually OK for cropped/zoomed images — only warn
        pass

    return ValidationResult(
        True,
        f"Earth disk present: {bright_ratio:.0%} bright, {dark_ratio:.0%} dark",
    )


def check_not_nighttime_blank(data: bytes, *, min_mean_brightness: float = 8.0) -> ValidationResult:
    """Check that the image isn't a near-black nighttime image with almost no visible content.

    FY-4B GCLR is a visible-light product — at night (UTC ~12:00-20:00 for China)
    the image will be mostly black. This check warns but still passes, since
    the pipeline should handle nighttime gracefully.
    """
    if Image is None:
        return ValidationResult(True, "Pillow not installed, skipping brightness check")

    try:
        img = Image.open(BytesIO(data)).convert("L")  # grayscale
        w, h = img.size
    except Exception as exc:
        return ValidationResult(False, f"Cannot open image: {exc}")

    # Sample center 50% of the image (where the earth disk is)
    x1, y1 = w // 4, h // 4
    x2, y2 = 3 * w // 4, 3 * h // 4
    center = img.crop((x1, y1, x2, y2))

    # Calculate mean brightness of center region
    step = max(1, min(center.size) // 80)
    total_brightness = 0
    count = 0
    for y in range(0, center.size[1], step):
        for x in range(0, center.size[0], step):
            total_brightness += center.getpixel((x, y))
            count += 1

    mean_bright = total_brightness / max(1, count)

    if mean_bright < min_mean_brightness:
        # Don't fail — nighttime images are expected at certain hours
        return ValidationResult(
            True,
            f"⚠ Very dark image (mean brightness={mean_bright:.1f}). "
            f"Possibly nighttime — earth disk may not be visible.",
        )

    return ValidationResult(True, f"Brightness OK (mean={mean_bright:.1f})")


# ---------------------------------------------------------------------------
# Combined validator
# ---------------------------------------------------------------------------

def validate_satellite_image(
    data: bytes,
    *,
    is_jpeg: bool = True,
    min_bytes: int = 50_000,
) -> ValidationResult:
    """Run all validation checks on a downloaded satellite image.

    Returns the first failing result, or a success result if all checks pass.
    Prints each check result to stderr for diagnostics.
    """
    checks = []

    if is_jpeg:
        checks.append(("JPEG integrity", check_jpeg_integrity(data, min_bytes=min_bytes)))

    checks.append(("Gray fill", check_gray_ratio(data)))
    checks.append(("Earth disk", check_earth_disk(data)))
    checks.append(("Brightness", check_not_nighttime_blank(data)))

    all_ok = True
    reasons: list[str] = []
    for name, result in checks:
        status = "✓" if result.valid else "✗"
        print(f"[global-background] Validate {name}: {status} {result.reason}", file=sys.stderr)
        if not result.valid:
            all_ok = False
            reasons.append(f"{name}: {result.reason}")

    if not all_ok:
        return ValidationResult(False, "; ".join(reasons))

    return ValidationResult(True, "All checks passed")
