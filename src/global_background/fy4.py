"""FY-4A / FY-4B full-disk image fetcher.

Downloads the latest full-disk JPEG from China's National Satellite
Meteorological Center (NSMC) at img.nsmc.org.cn.

Available endpoints (verified 2026-02):
  FY-4A  MTCC (multi-channel true-colour composite, ~2200x2200, ~800 KB)
    http://img.nsmc.org.cn/CLOUDIMAGE/FY4A/MTCC/FY4A_DISK.jpg

  FY-4B  GCLR (AGRI geo-colour, ~11000x12000, ~11 MB)
    http://img.nsmc.org.cn/CLOUDIMAGE/FY4B/AGRI/GCLR/FY4B_DISK_GCLR.jpg

These URLs always serve the **latest** image; there is no timestamp API.
We parse the Last-Modified header (if present) for the image timestamp.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Final
from urllib.request import Request, urlopen

from .system_proxy import system_proxy_env_for_url


class _DownloadTruncatedError(Exception):
    """Raised when a FY-4 download is incomplete (missing bytes or JPEG EOI marker)."""


# ---------------------------------------------------------------------------
# Known endpoints
# ---------------------------------------------------------------------------

_ENDPOINTS: dict[tuple[str, str], str] = {
    # (satellite, product) -> URL
    ("fy4a", "mtcc"): "http://img.nsmc.org.cn/CLOUDIMAGE/FY4A/MTCC/FY4A_DISK.jpg",
    ("fy4b", "gclr"): "http://img.nsmc.org.cn/CLOUDIMAGE/FY4B/AGRI/GCLR/FY4B_DISK_GCLR.jpg",
}


@dataclass(frozen=True)
class FY4FullDiskRequest:
    satellite: str = "fy4a"  # "fy4a" | "fy4b"
    product: str = "mtcc"    # "mtcc" (FY4A) | "gclr" (FY4B)


def _resolve_url(req: FY4FullDiskRequest) -> str:
    sat = req.satellite.strip().lower()
    prod = req.product.strip().lower()
    url = _ENDPOINTS.get((sat, prod))
    if url is None:
        raise ValueError(
            f"Unknown FY-4 endpoint: satellite={sat!r} product={prod!r}. "
            f"Supported: {list(_ENDPOINTS.keys())}"
        )
    return url


def fetch_latest_full_disk_jpg(
    req: FY4FullDiskRequest,
    *,
    timeout_s: float = 30.0,
) -> tuple[bytes, dt.datetime, str]:
    """Fetch the latest FY-4 full-disk JPEG.

    Uses chunked reading with retries to handle large files (FY4B GCLR ~11-20 MB)
    over slow/unreliable enterprise proxy connections.

    Returns: (jpeg_bytes, timestamp_utc, url)
    """

    url = _resolve_url(req)

    max_retries = 5
    chunk_size = 256 * 1024  # 256 KB chunks

    _JPEG_EOI: Final[bytes] = b"\xff\xd9"

    last_exc: Exception | None = None
    headers_out = None

    def _read_all(resp) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def _parse_int_header(val: str | None) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except Exception:
            return None

    def _download_with_resume(url0: str) -> tuple[bytes, object]:
        """Download bytes, resuming with Range/If-Range if truncated.

        Returns (data, headers). Raises _DownloadTruncatedError on failure.
        """

        base_headers: dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) global-background/0.1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            # Some enterprise proxies/servers behave better without keep-alive.
            "Connection": "close",
        }

        with system_proxy_env_for_url(url0):
            # First request
            first_req = Request(url0, headers=base_headers)
            with urlopen(first_req, timeout=float(timeout_s)) as resp:
                headers = resp.headers
                expected = _parse_int_header(headers.get("Content-Length"))
                etag = headers.get("ETag")
                last_modified = headers.get("Last-Modified")
                data = _read_all(resp)

            if not data or len(data) < 10_000:
                raise RuntimeError(f"FY-4 response too small ({len(data)} bytes), likely a placeholder")

            def _looks_complete(buf: bytes, expected_len: int | None) -> bool:
                if expected_len is not None and len(buf) < expected_len:
                    return False
                if buf.endswith(_JPEG_EOI):
                    return True
                tail = buf[-16:]
                return _JPEG_EOI in tail

            if _looks_complete(data, expected):
                return data, headers

            # If server told us the size, try resuming missing bytes.
            # If it didn't, we can still try a limited number of resume attempts
            # until we see the JPEG EOI marker.
            max_resume_requests = 5
            for _ in range(max_resume_requests):
                start = len(data)
                if expected is not None and start >= expected:
                    break

                resume_headers = dict(base_headers)
                resume_headers["Range"] = f"bytes={start}-"
                # Prevent mixing bytes across different "latest" images.
                if etag:
                    resume_headers["If-Range"] = etag
                elif last_modified:
                    resume_headers["If-Range"] = last_modified

                resume_req = Request(url0, headers=resume_headers)
                with urlopen(resume_req, timeout=float(timeout_s)) as resp2:
                    # If server/proxy ignores Range, it may return 200 with full content.
                    # In that case, replace buffer and restart completeness check.
                    code = getattr(resp2, "status", None)
                    headers2 = resp2.headers

                    # Update metadata if present.
                    if headers2.get("ETag"):
                        etag = headers2.get("ETag")
                    if headers2.get("Last-Modified"):
                        last_modified = headers2.get("Last-Modified")

                    # Content-Length for 206 is the remaining bytes, not total.
                    # Content-Range includes total: bytes start-end/total
                    cr = headers2.get("Content-Range")
                    if cr and "/" in cr:
                        try:
                            total = int(cr.split("/")[-1].strip())
                            if total > 0:
                                expected = total
                        except Exception:
                            pass
                    elif expected is None:
                        expected = _parse_int_header(headers2.get("Content-Length"))

                    more = _read_all(resp2)

                    if code == 200:
                        data = more
                    else:
                        data += more

                if _looks_complete(data, expected):
                    return data, headers2

            # Still incomplete after resume attempts
            if expected is not None and len(data) < expected:
                raise _DownloadTruncatedError(
                    f"FY-4 download truncated: got {len(data):,} / {expected:,} bytes "
                    f"({len(data)*100//expected}%)"
                )
            raise _DownloadTruncatedError(
                f"FY-4 JPEG incomplete: missing FFD9 end marker "
                f"(got {len(data):,} bytes, tail={data[-4:].hex()})"
            )

    for attempt in range(max_retries):
        try:
            data, headers_out = _download_with_resume(url)

            # Success — download is complete
            break
        except _DownloadTruncatedError as exc:
            last_exc = exc
            import time, sys as _sys
            print(
                f"[global-background] FY-4 download truncated (attempt {attempt+1}/{max_retries}): {exc}",
                file=_sys.stderr,
            )
            if attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(
                f"FY-4 download still truncated after {max_retries} attempts: {exc}"
            ) from exc
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                import time
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(
                f"FY-4 download failed after {max_retries} attempts (last error: {last_exc!r})"
            ) from last_exc

    # Try to extract timestamp from Last-Modified header
    ts_utc = dt.datetime.now(dt.timezone.utc)
    if headers_out is not None:
        lm = headers_out.get("Last-Modified")
        if lm:
            try:
                ts_utc = parsedate_to_datetime(lm).astimezone(dt.timezone.utc)
            except Exception:
                pass

    return data, ts_utc, url
