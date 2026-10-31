"""Shared HTTP plumbing for every NOAA feed.

One place for the User-Agent (api.weather.gov refuses requests without one), conditional requests, and a small retry
loop. It deliberately knows nothing about any feed: providers pass a URL and get bytes back.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from eyewall import __version__

PROJECT_URL = "https://github.com/WPTK/eyewall"
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
MAX_RETRY_AFTER = 30.0


def user_agent() -> str:
    return f"eyewall/{__version__} (+{PROJECT_URL})"


def new_client(*, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """An HTTP client with eyewall's User-Agent and timeouts. The caller closes it."""
    return httpx.AsyncClient(
        headers={"User-Agent": user_agent()},
        timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        follow_redirects=True,
        transport=transport,
    )


class FetchError(Exception):
    """A fetch that did not produce a usable response."""

    def __init__(self, url: str, message: str) -> None:
        super().__init__(f"{url}: {message}")
        self.url = url


class NetworkError(FetchError):
    """No response at all: DNS, connection, TLS or timeout."""


class HttpError(FetchError):
    def __init__(self, url: str, status: int) -> None:
        super().__init__(url, f"HTTP {status}")
        self.status = status


class RateLimited(HttpError):
    def __init__(self, url: str, retry_after: float | None) -> None:
        super().__init__(url, 429)
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    status: int
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    @property
    def missing(self) -> bool:
        return self.status == 404

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a Retry-After header. HTTP-date values are ignored."""
    try:
        return max(0.0, float(response.headers["Retry-After"]))
    except (KeyError, ValueError):
        return None


async def fetch_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    allow_404: bool = False,
    retries: int = 2,
    backoff: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Fetched:
    """GET a URL, retrying transport errors, 429 and 5xx with backoff.

    A 304 comes back as a Fetched with not_modified set. A 404 comes back the same way, as missing, only when
    allow_404 is true (a buoy that stopped reporting is normal, not an error). Anything else raises a FetchError.
    """
    request_headers = dict(headers or {})
    if etag:
        request_headers["If-None-Match"] = etag
    if last_modified:
        request_headers["If-Modified-Since"] = last_modified
    attempt = 0
    while True:
        try:
            response = await client.get(url, params=params, headers=request_headers)
        except httpx.TransportError as exc:
            if attempt >= retries:
                raise NetworkError(url, str(exc) or type(exc).__name__) from exc
            await sleep(backoff * 2**attempt)
            attempt += 1
            continue
        status = response.status_code
        if 200 <= status < 300 or status == 304:
            return Fetched(
                url, status, response.content, response.headers.get("ETag"), response.headers.get("Last-Modified")
            )
        if status == 404 and allow_404:
            return Fetched(url, 404)
        if status == 429 or status >= 500:
            retry_after = _retry_after(response)
            if attempt >= retries:
                raise RateLimited(url, retry_after) if status == 429 else HttpError(url, status)
            delay = min(retry_after, MAX_RETRY_AFTER) if retry_after is not None else backoff * 2**attempt
            await sleep(delay)
            attempt += 1
            continue
        raise HttpError(url, status)
