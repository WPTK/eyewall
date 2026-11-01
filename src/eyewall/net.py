"""Shared HTTP plumbing for every NOAA feed.

One place for the User-Agent (api.weather.gov refuses requests without one), conditional requests, and a small retry
loop. It deliberately knows nothing about any feed: providers pass a URL and get bytes back.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from eyewall import __version__

PROJECT_URL = "https://github.com/WPTK/eyewall"
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
MAX_RETRY_AFTER = 30.0
RETRIES = 2  # retries after the first attempt, for a transport error, 429 or 5xx
ERROR_BODY_LIMIT = 64 * 1024  # an error page is read to the end (so the connection is reused) only if it is this small
MAX_BYTES_EXTENSION = (
    "eyewall_max_bytes"  # request extension: the caller's body limit, so the cache can skip a body it would reject
)


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
    """No usable response: DNS, connection, TLS or timeout, or a body that cannot be read (bad encoding, loop)."""


class HttpError(FetchError):
    def __init__(self, url: str, status: int) -> None:
        super().__init__(url, f"HTTP {status}")
        self.status = status


class TooLarge(FetchError):
    """A body over the caller's size limit; the download was abandoned at the first byte past it."""

    def __init__(self, url: str, limit: int) -> None:
        super().__init__(url, f"more than {limit // (1024 * 1024)} MB, over the limit")
        self.limit = limit


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


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds from a Retry-After header, which is either a number of seconds or an HTTP-date."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, seconds) if math.isfinite(seconds) else None


def retry_delay(retry_after: float | None, attempt: int, backoff: float = 1.0) -> float:
    """How long to wait before retry number `attempt`: the server's Retry-After (capped), else exponential backoff."""
    return min(retry_after, MAX_RETRY_AFTER) if retry_after is not None else backoff * 2**attempt


async def fetch_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    allow_404: bool = False,
    max_bytes: int | None = None,
    retries: int = RETRIES,
    backoff: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Fetched:
    """GET a URL, retrying transport errors, 429 and 5xx with backoff.

    A 304 comes back as a Fetched with not_modified set. A 404 comes back the same way, as missing, only when
    allow_404 is true (a buoy that stopped reporting is normal, not an error). Anything else raises a FetchError.

    With `max_bytes` the body is streamed: a `Content-Length` over the limit, or the first byte past it, raises
    `TooLarge` without buffering the rest. Without it the whole body is read, as before.
    """
    request_headers = dict(headers or {})
    if etag:
        request_headers["If-None-Match"] = etag
    if last_modified:
        request_headers["If-Modified-Since"] = last_modified
    attempt = 0
    while True:
        try:
            async with client.stream(
                "GET",
                url,
                params=params,
                headers=request_headers,
                extensions={} if max_bytes is None else {MAX_BYTES_EXTENSION: max_bytes},
            ) as response:
                status = response.status_code
                if 200 <= status < 300 or status == 304:
                    body = await _read_body(response, url, max_bytes) if status != 304 else b""
                    return Fetched(
                        url, status, body, response.headers.get("ETag"), response.headers.get("Last-Modified")
                    )
                await drain_body(response)
                if status == 404 and allow_404:
                    return Fetched(url, 404)
                retry_after = retry_after_seconds(response)
        except httpx.RequestError as exc:  # transport errors, but also DecodingError and TooManyRedirects
            if attempt >= retries:
                raise NetworkError(url, str(exc) or type(exc).__name__) from exc
            await sleep(backoff * 2**attempt)
            attempt += 1
            continue
        if status == 429 or status >= 500:
            if attempt >= retries:
                raise RateLimited(url, retry_after) if status == 429 else HttpError(url, status)
            await sleep(retry_delay(retry_after, attempt, backoff))
            attempt += 1
            continue
        raise HttpError(url, status)


async def drain_body(response: httpx.Response) -> None:
    """Read a small error body to its end so the keep-alive connection goes back to the pool; a big one is dropped."""
    size = 0
    try:
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > ERROR_BODY_LIMIT:
                return
    except httpx.RequestError:
        return  # the status is already known; a broken body is not worth a retry


async def _read_body(response: httpx.Response, url: str, max_bytes: int | None) -> bytes:
    """The decoded body; with a limit, stop reading at the first byte over it."""
    if max_bytes is None:
        return await response.aread()
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise TooLarge(url, max_bytes)
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise TooLarge(url, max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
