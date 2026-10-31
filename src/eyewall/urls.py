"""Address checks shared by the parsers, the downloads and the open-link action."""

from __future__ import annotations

from urllib.parse import urlsplit

NOAA_DOMAINS = ("noaa.gov", "weather.gov")


def is_noaa_url(url: str) -> bool:
    """True for an https address whose parsed host is noaa.gov or weather.gov or a subdomain of either.

    Browsers read a backslash as a slash, so a backslash before an at sign can send a browser to a different host
    than `urlsplit` reports. Anything with a backslash, a control character or a space, a user name or a
    port other than 443 is refused rather than interpreted.
    """
    if not url or any(ch == "\\" or ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return False
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or "@" in parts.netloc or port not in (None, 443):
        return False
    if not host or any(not (ch.isascii() and (ch.isalnum() or ch in ".-")) for ch in host):
        return False
    return any(host == d or host.endswith("." + d) for d in NOAA_DOMAINS)
