from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from functools import lru_cache
from urllib.parse import urlparse


def _has_any_proxy_env() -> bool:
    return any(
        os.environ.get(k)
        for k in [
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
        ]
    )


def _normalize_proxy_token(token: str) -> str:
    t = token.strip()
    if not t:
        return t
    if t.upper().startswith("PROXY "):
        t = t[6:].strip()
    if "://" not in t:
        t = f"http://{t}"
    return t


def _parse_proxy_string(raw: str) -> dict[str, str]:
    """Parse WinHTTP/IE proxy string into {'http': ..., 'https': ...}.

    Handles formats like:
      - "proxy:8080"
      - "http=proxy:8080;https=proxy:8080"
      - "PROXY proxy:8080; DIRECT"
    """

    raw = (raw or "").strip()
    if not raw:
        return {}

    # If it's a simple token (no ';' and no '=') treat as single proxy.
    if ";" not in raw and "=" not in raw:
        p = _normalize_proxy_token(raw)
        return {"http": p, "https": p} if p else {}

    proxies: dict[str, str] = {}
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    for part in parts:
        upper = part.upper()
        if upper == "DIRECT":
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip().lower()
            v = _normalize_proxy_token(v)
            if k in {"http", "https"} and v:
                proxies[k] = v
            continue
        # e.g. "PROXY proxy:8080"
        v = _normalize_proxy_token(part)
        if v:
            proxies.setdefault("http", v)
            proxies.setdefault("https", v)

    return proxies


def _proxy_cache_key(url: str) -> str | None:
    try:
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return None
        # For PAC, proxy selection is almost always host-based; strip query/fragment.
        return f"{p.scheme}://{p.netloc}/"
    except Exception:
        return None


@lru_cache(maxsize=64)
def _winhttp_proxy_for_key(key_url: str) -> str | None:
    if not sys.platform.startswith("win"):
        return None

    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    winhttp = ctypes.WinDLL("winhttp")
    kernel32 = ctypes.WinDLL("kernel32")

    class WINHTTP_CURRENT_USER_IE_PROXY_CONFIG(ctypes.Structure):
        _fields_ = [
            ("fAutoDetect", wintypes.BOOL),
            # Use void* to avoid ctypes auto-converting LPWSTR into Python str.
            ("lpszAutoConfigUrl", ctypes.c_void_p),
            ("lpszProxy", ctypes.c_void_p),
            ("lpszProxyBypass", ctypes.c_void_p),
        ]

    class WINHTTP_AUTOPROXY_OPTIONS(ctypes.Structure):
        _fields_ = [
            ("dwFlags", wintypes.DWORD),
            ("dwAutoDetectFlags", wintypes.DWORD),
            ("lpszAutoConfigUrl", wintypes.LPCWSTR),
            ("lpvReserved", wintypes.LPVOID),
            ("dwReserved", wintypes.DWORD),
            ("fAutoLogonIfChallenged", wintypes.BOOL),
        ]

    class WINHTTP_PROXY_INFO(ctypes.Structure):
        _fields_ = [
            ("dwAccessType", wintypes.DWORD),
            ("lpszProxy", ctypes.c_void_p),
            ("lpszProxyBypass", ctypes.c_void_p),
        ]

    WinHttpGetIEProxyConfigForCurrentUser = winhttp.WinHttpGetIEProxyConfigForCurrentUser
    WinHttpGetIEProxyConfigForCurrentUser.argtypes = [ctypes.POINTER(WINHTTP_CURRENT_USER_IE_PROXY_CONFIG)]
    WinHttpGetIEProxyConfigForCurrentUser.restype = wintypes.BOOL

    WinHttpOpen = winhttp.WinHttpOpen
    WinHttpOpen.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    WinHttpOpen.restype = wintypes.HANDLE

    WinHttpCloseHandle = winhttp.WinHttpCloseHandle
    WinHttpCloseHandle.argtypes = [wintypes.HANDLE]
    WinHttpCloseHandle.restype = wintypes.BOOL

    WinHttpGetProxyForUrl = winhttp.WinHttpGetProxyForUrl
    WinHttpGetProxyForUrl.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        ctypes.POINTER(WINHTTP_AUTOPROXY_OPTIONS),
        ctypes.POINTER(WINHTTP_PROXY_INFO),
    ]
    WinHttpGetProxyForUrl.restype = wintypes.BOOL

    GlobalFree = kernel32.GlobalFree
    GlobalFree.argtypes = [wintypes.HGLOBAL]
    GlobalFree.restype = wintypes.HGLOBAL

    WINHTTP_ACCESS_TYPE_NO_PROXY = 1
    WINHTTP_AUTOPROXY_AUTO_DETECT = 0x00000001
    WINHTTP_AUTOPROXY_CONFIG_URL = 0x00000002
    WINHTTP_AUTOPROXY_RUN_INPROCESS = 0x00010000
    WINHTTP_AUTO_DETECT_TYPE_DHCP = 0x00000001
    WINHTTP_AUTO_DETECT_TYPE_DNS_A = 0x00000002

    def _ptr_to_str(ptr: int | None) -> str | None:
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        except Exception:
            return None

    ie = WINHTTP_CURRENT_USER_IE_PROXY_CONFIG()
    if not WinHttpGetIEProxyConfigForCurrentUser(ctypes.byref(ie)):
        return None

    try:
        # If an explicit proxy is configured, prefer it.
        if ie.lpszProxy:
            s = _ptr_to_str(int(ie.lpszProxy))
            return s

        session = WinHttpOpen("global-background/0.1", WINHTTP_ACCESS_TYPE_NO_PROXY, None, None, 0)
        if not session:
            return None
        try:
            opt = WINHTTP_AUTOPROXY_OPTIONS()
            opt.fAutoLogonIfChallenged = True
            opt.lpvReserved = None
            opt.dwReserved = 0
            opt.dwAutoDetectFlags = 0

            if ie.lpszAutoConfigUrl:
                opt.dwFlags = WINHTTP_AUTOPROXY_CONFIG_URL | WINHTTP_AUTOPROXY_RUN_INPROCESS
                opt.lpszAutoConfigUrl = ctypes.cast(ie.lpszAutoConfigUrl, wintypes.LPCWSTR)
            elif ie.fAutoDetect:
                opt.dwFlags = WINHTTP_AUTOPROXY_AUTO_DETECT | WINHTTP_AUTOPROXY_RUN_INPROCESS
                opt.dwAutoDetectFlags = WINHTTP_AUTO_DETECT_TYPE_DHCP | WINHTTP_AUTO_DETECT_TYPE_DNS_A
                opt.lpszAutoConfigUrl = None
            else:
                return None

            info = WINHTTP_PROXY_INFO()
            if not WinHttpGetProxyForUrl(session, key_url, ctypes.byref(opt), ctypes.byref(info)):
                return None
            try:
                if not info.lpszProxy:
                    return None
                return _ptr_to_str(int(info.lpszProxy))
            finally:
                try:
                    if info.lpszProxy:
                        GlobalFree(wintypes.HGLOBAL(int(info.lpszProxy)))
                    if info.lpszProxyBypass:
                        GlobalFree(wintypes.HGLOBAL(int(info.lpszProxyBypass)))
                except Exception:
                    pass
        finally:
            try:
                WinHttpCloseHandle(session)
            except Exception:
                pass
    finally:
        try:
            # These are allocated by WinHTTP and must be freed.
            if ie.lpszAutoConfigUrl:
                GlobalFree(wintypes.HGLOBAL(int(ie.lpszAutoConfigUrl)))
            if ie.lpszProxy:
                GlobalFree(wintypes.HGLOBAL(int(ie.lpszProxy)))
            if ie.lpszProxyBypass:
                GlobalFree(wintypes.HGLOBAL(int(ie.lpszProxyBypass)))
        except Exception:
            pass


def get_system_proxies_for_url(url: str) -> dict[str, str]:
    """Return proxies for a URL via WinHTTP auto-proxy (Windows) or {}."""

    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return {}
    except Exception:
        return {}

    key = _proxy_cache_key(url)
    if not key:
        return {}

    raw = _winhttp_proxy_for_key(key)
    if not raw:
        return {}
    return _parse_proxy_string(raw)


@contextmanager
def system_proxy_env_for_url(url: str):
    """Temporarily apply system proxy (PAC/WPAD) for this URL if no proxy env is set."""

    if _has_any_proxy_env():
        yield
        return

    proxies = get_system_proxies_for_url(url)
    if not proxies:
        yield
        return

    keys = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]
    old = {k: os.environ.get(k) for k in keys}
    try:
        if proxies.get("http"):
            os.environ["HTTP_PROXY"] = proxies["http"]
            os.environ["http_proxy"] = proxies["http"]
        if proxies.get("https"):
            os.environ["HTTPS_PROXY"] = proxies["https"]
            os.environ["https_proxy"] = proxies["https"]
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
