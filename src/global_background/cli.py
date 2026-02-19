from __future__ import annotations

import argparse
import time
from pathlib import Path

from .config import AppConfig, load_config
from .pipeline import run_once
from .validate import ImageValidationError
from .wallpaper import set_wallpaper
from .bmpgen import write_solid_bmp

# Max retries when image validation fails (1 retry per minute)
_VALIDATION_MAX_RETRIES = 10
_VALIDATION_RETRY_INTERVAL_S = 60


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="global-background")
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to config file: .toml (recommended), .yaml/.yml, or .json (default: config.toml)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    once = sub.add_parser("once", help="Fetch one image and set wallpaper")
    once.add_argument(
        "--config",
        default="config.toml",
        help="Path to config file: .toml (recommended), .yaml/.yml, or .json (default: config.toml)",
    )
    once.add_argument("--dry-run", action="store_true", help="Do not set wallpaper")

    run = sub.add_parser("run", help="Loop forever, running once every interval")
    run.add_argument(
        "--config",
        default="config.toml",
        help="Path to config file: .toml (recommended), .yaml/.yml, or .json (default: config.toml)",
    )
    run.add_argument("--dry-run", action="store_true", help="Do not set wallpaper")

    setp = sub.add_parser("set", help="Set wallpaper from an existing local image")
    setp.add_argument("--path", required=True, help="Path to image (bmp/jpg/png)")
    setp.add_argument("--style", default="fill", help="fill|fit|stretch|center|span")

    demo = sub.add_parser("demo", help="Generate a local BMP wallpaper (offline test)")
    demo.add_argument("--width", type=int, default=1920)
    demo.add_argument("--height", type=int, default=1080)
    demo.add_argument("--rgb", default="20,40,60", help="Solid color as r,g,b (0-255)")
    demo.add_argument("--style", default="fill", help="fill|fit|stretch|center|span")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    cfg: AppConfig = load_config(config_path)

    if args.command == "once":
        for attempt in range(1, _VALIDATION_MAX_RETRIES + 1):
            try:
                run_once(cfg, dry_run=bool(args.dry_run))
                return 0
            except ImageValidationError as exc:
                import sys as _sys
                print(
                    f"[global-background] Image validation failed (attempt {attempt}/{_VALIDATION_MAX_RETRIES}): {exc}",
                    file=_sys.stderr,
                )
                if attempt < _VALIDATION_MAX_RETRIES:
                    print(
                        f"[global-background] Wallpaper NOT updated. Retrying in {_VALIDATION_RETRY_INTERVAL_S}s...",
                        file=_sys.stderr,
                    )
                    time.sleep(_VALIDATION_RETRY_INTERVAL_S)
                else:
                    print(
                        f"[global-background] All {_VALIDATION_MAX_RETRIES} attempts failed. Wallpaper NOT updated.",
                        file=_sys.stderr,
                    )
        return 1

    if args.command == "run":
        while True:
            start = time.time()
            try:
                # Inner retry loop for validation failures
                for attempt in range(1, _VALIDATION_MAX_RETRIES + 1):
                    try:
                        run_once(cfg, dry_run=bool(args.dry_run))
                        break  # success
                    except ImageValidationError as exc:
                        import sys as _sys
                        print(
                            f"[global-background] Image validation failed (attempt {attempt}/{_VALIDATION_MAX_RETRIES}): {exc}",
                            file=_sys.stderr,
                        )
                        if attempt < _VALIDATION_MAX_RETRIES:
                            print(
                                f"[global-background] Wallpaper NOT updated. Retrying in {_VALIDATION_RETRY_INTERVAL_S}s...",
                                file=_sys.stderr,
                            )
                            time.sleep(_VALIDATION_RETRY_INTERVAL_S)
                        else:
                            print(
                                f"[global-background] All {_VALIDATION_MAX_RETRIES} attempts failed. Wallpaper NOT updated this cycle.",
                                file=_sys.stderr,
                            )
            except Exception as exc:
                out_dir = Path(cfg.output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "errors.log").write_text(f"{exc!r}\n", encoding="utf-8")

            elapsed = time.time() - start
            sleep_s = max(5.0, cfg.update_interval_minutes * 60.0 - elapsed)
            time.sleep(sleep_s)

    if args.command == "set":
        set_wallpaper(Path(args.path), style=str(args.style))
        return 0

    if args.command == "demo":
        out_dir = Path("out")
        day_dir = out_dir / time.strftime("%Y-%m-%d")
        stamp = time.strftime("%Y%m%d_%H%M%S")
        bmp_path = day_dir / f"demo_{stamp}.bmp"

        parts = [p.strip() for p in str(args.rgb).split(",")]
        if len(parts) != 3:
            raise SystemExit("--rgb must be r,g,b")
        rgb = (int(parts[0]), int(parts[1]), int(parts[2]))
        write_solid_bmp(bmp_path, int(args.width), int(args.height), rgb)
        set_wallpaper(bmp_path, style=str(args.style))
        return 0

    return 0
