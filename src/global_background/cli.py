from __future__ import annotations

import argparse
import datetime as dt
import sys
import threading
import time
from pathlib import Path

from .config import AppConfig, load_config
from .pipeline import run_once, run_hourly_slot, run_frame_slot
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

    loop = sub.add_parser(
        "loop",
        help=(
            "24-hour animated wallpaper: download one image per hour and cycle "
            "through them as a slideshow"
        ),
    )
    loop.add_argument(
        "--config",
        default="config.toml",
        help="Path to config file (default: config.toml)",
    )
    loop.add_argument("--dry-run", action="store_true", help="Populate ring buffer but do not set wallpaper")

    setp = sub.add_parser("set", help="Set wallpaper from an existing local image")
    setp.add_argument("--path", required=True, help="Path to image (bmp/jpg/png)")
    setp.add_argument("--style", default="fill", help="fill|fit|stretch|center|span")

    demo = sub.add_parser("demo", help="Generate a local BMP wallpaper (offline test)")
    demo.add_argument("--width", type=int, default=1920)
    demo.add_argument("--height", type=int, default=1080)
    demo.add_argument("--rgb", default="20,40,60", help="Solid color as r,g,b (0-255)")
    demo.add_argument("--style", default="fill", help="fill|fit|stretch|center|span")

    return parser


def _run_loop(cfg: AppConfig, dry_run: bool = False) -> None:
    """
    Animated wallpaper loop: download every ``frame_interval_min`` minutes,
    play through the ring buffer at ``play_interval_s`` seconds per frame.

    Two concurrent activities:
    1. **Downloader** (background thread): Fetches the latest frame at each
       clock-aligned tick (e.g. :00/:15/:30/:45 for 15-min intervals) and
       writes it to the ring-buffer slot for that time.
    2. **Player** (main thread): Cycles through available frames at
       ``play_interval_s`` seconds per frame.

    Images are stored in ``{output_dir}/frames/f{idx:04d}.{ext}``
    where idx = (hour * 60 + minute) // frame_interval_min  (0-95 for 15-min).
    """
    play_interval_s = max(1, int(cfg.slideshow.play_interval_s))
    frame_interval_min = max(1, int(cfg.slideshow.frame_interval_min))
    slots_per_day = 24 * 60 // frame_interval_min  # e.g. 96 for 15-min
    frames_dir = Path(cfg.output_dir) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Helper: next clock-aligned download tick
    # ------------------------------------------------------------------
    def _next_tick(now: dt.datetime) -> dt.datetime:
        now_min = now.hour * 60 + now.minute
        next_min = ((now_min // frame_interval_min) + 1) * frame_interval_min
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return base + dt.timedelta(minutes=next_min)  # handles next-day rollover

    # ------------------------------------------------------------------
    # Helper: list available frames sorted by slot index
    # ------------------------------------------------------------------
    def _list_frames() -> list[Path]:
        candidates: dict[int, Path] = {}
        # Prefer .bmp (Windows), then .jpg, then .png for each slot.
        for ext in (".bmp", ".jpg", ".png"):
            for p in frames_dir.glob(f"f????{ext}"):
                try:
                    idx = int(p.stem[1:])
                except ValueError:
                    continue
                if idx not in candidates:
                    candidates[idx] = p
        return [candidates[k] for k in sorted(candidates)]

    # ------------------------------------------------------------------
    # Helper: fetch one frame slot with retry
    # ------------------------------------------------------------------
    MAX_SLOT_RETRIES = 2

    def _fetch_slot(target: dt.datetime) -> None:
        t = target.astimezone(dt.timezone.utc)
        idx = (t.hour * 60 + t.minute) // frame_interval_min
        for attempt in range(1, MAX_SLOT_RETRIES + 1):
            try:
                run_frame_slot(cfg, target, dry_run=False)
                return
            except Exception as exc:
                print(
                    f"[loop] Slot f{idx:04d} attempt {attempt}/{MAX_SLOT_RETRIES} failed: {exc}",
                    file=sys.stderr,
                )
                if attempt < MAX_SLOT_RETRIES:
                    time.sleep(15)
        print(f"[loop] Giving up on slot f{idx:04d} for now.", file=sys.stderr)

    # ------------------------------------------------------------------
    # Fetch the current slot immediately on startup
    # ------------------------------------------------------------------
    now_utc = dt.datetime.now(dt.timezone.utc)
    print(
        f"[loop] Starting slideshow loop ({slots_per_day} slots/day, "
        f"download every {frame_interval_min}min, play at {play_interval_s}s/frame).",
        file=sys.stderr,
    )
    cur_min = (now_utc.hour * 60 + now_utc.minute) // frame_interval_min * frame_interval_min
    current_slot_time = now_utc.replace(
        hour=cur_min // 60, minute=cur_min % 60, second=0, microsecond=0
    )
    _fetch_slot(current_slot_time)

    # ------------------------------------------------------------------
    # Background downloader thread: wake at each aligned tick
    # ------------------------------------------------------------------
    def _download_thread() -> None:
        while True:
            now = dt.datetime.now(dt.timezone.utc)
            tick = _next_tick(now)
            sleep_s = (tick - now).total_seconds()
            # Sleep in short bursts so the daemon thread can exit cleanly
            while sleep_s > 0:
                time.sleep(min(sleep_s, 10))
                sleep_s -= 10

            target = dt.datetime.now(dt.timezone.utc)
            t_idx = (target.hour * 60 + target.minute) // frame_interval_min
            print(
                f"[loop] Tick {target.strftime('%H:%M')} UTC — downloading slot f{t_idx:04d}…",
                file=sys.stderr,
            )
            _fetch_slot(target)

    dl_thread = threading.Thread(target=_download_thread, daemon=True, name="gb-downloader")
    dl_thread.start()

    # ------------------------------------------------------------------
    # Main thread: player loop
    # ------------------------------------------------------------------
    frame_idx = 0
    print(
        f"[loop] Player started ({play_interval_s}s/frame). Press Ctrl-C to stop.",
        file=sys.stderr,
    )
    while True:
        frames = _list_frames()
        if frames:
            path = frames[frame_idx % len(frames)]
            if not dry_run:
                try:
                    set_wallpaper(path, style=cfg.wallpaper.style)
                except Exception as exc:
                    print(f"[loop] set_wallpaper failed: {exc}", file=sys.stderr)
            frame_idx += 1
            print(
                f"[loop] Frame {frame_idx}: {path.name}  ({len(frames)}/{slots_per_day} slots)",
                file=sys.stderr,
            )
        else:
            print("[loop] No frames available yet, waiting…", file=sys.stderr)

        time.sleep(play_interval_s)


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
            except Exception as exc:
                import sys as _sys
                print(
                    f"[global-background] Fetch failed (attempt {attempt}/{_VALIDATION_MAX_RETRIES}): {exc}",
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
            for attempt in range(1, _VALIDATION_MAX_RETRIES + 1):
                try:
                    run_once(cfg, dry_run=bool(args.dry_run))
                    break  # success
                except Exception as exc:
                    import sys as _sys
                    print(
                        f"[global-background] Fetch failed (attempt {attempt}/{_VALIDATION_MAX_RETRIES}): {exc}",
                        file=_sys.stderr,
                    )
                    # Log to file
                    out_dir = Path(cfg.output_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / "errors.log").write_text(
                        f"attempt {attempt}: {exc!r}\n", encoding="utf-8"
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

            elapsed = time.time() - start
            sleep_s = max(5.0, cfg.update_interval_minutes * 60.0 - elapsed)
            time.sleep(sleep_s)

    if args.command == "loop":
        _run_loop(cfg, dry_run=bool(args.dry_run))
        return 0  # only reached on Ctrl-C / exception

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
