from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowsProxySettings:
    http_proxy: str | None
    https_proxy: str | None
    raw: str | None


def _ensure_scheme(proxy: str) -> str:
    p = proxy.strip()
    if not p:
        return p
    if "://" in p:
        return p
    return f"http://{p}"


def get_windows_proxy_settings() -> WindowsProxySettings | None:
    """Best-effort read of the current user's WinINET proxy settings.

    This typically matches the system proxy used by Edge/IE and many corporate networks.
    Supports the common `ProxyServer` formats:
      - "proxy.example.com:8080"
      - "http=proxy:8080;https=proxy:8080"
    PAC/AutoConfigURL is not evaluated.
    """

    try:
        import winreg  # type: ignore
    except Exception:
        return None

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not int(proxy_enable):
                return WindowsProxySettings(http_proxy=None, https_proxy=None, raw=None)
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except Exception:
        return None

    raw = str(proxy_server).strip() if proxy_server is not None else ""
    if not raw:
        return WindowsProxySettings(http_proxy=None, https_proxy=None, raw=None)

    http_proxy: str | None = None
    https_proxy: str | None = None

    if "=" in raw:
        # e.g. "http=proxy:8080;https=proxy:8080"
        for part in raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if not v:
                continue
            if k == "http":
                http_proxy = _ensure_scheme(v)
            elif k == "https":
                https_proxy = _ensure_scheme(v)
    else:
        # Single proxy for everything.
        http_proxy = _ensure_scheme(raw)
        https_proxy = _ensure_scheme(raw)

    return WindowsProxySettings(http_proxy=http_proxy, https_proxy=https_proxy, raw=raw)
