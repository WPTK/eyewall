"""A disk cache of raw responses, so a launch paints instantly and an offline launch shows the last data.

The cache sits under the HTTP client as a transport (`CachingTransport`), which makes it work for every feed without
the parsers knowing about it:

- A GET whose URL is cached is sent with the saved `ETag` / `Last-Modified` as validators. A 304 comes back to the
  caller as the cached 200, so a feed that has not changed costs a header exchange and no body.
- A 2xx answer replaces the cached copy.
- When the network fails (no connection, a timeout) or the server answers 429 or 5xx, and a copy exists, the caller
  gets the copy and the current `StaleMarker` is set, so the live source can say the feed is stale. With no copy the
  failure propagates as usual.

Entries live under `platformdirs.user_cache_dir("eyewall")` as a `.json` metadata file and a `.bin` raw body (still
compressed if the server compressed it, so the client decodes it the same way as a fresh answer).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from platformdirs import user_cache_dir

MAX_BODY_BYTES = 32 * 1024 * 1024
_KEPT_HEADERS = ("etag", "last-modified", "content-type", "content-encoding")
_FAILURE_STATUSES = frozenset({429, 500, 502, 503, 504})


def default_cache_dir() -> Path:
    return Path(user_cache_dir("eyewall", appauthor=False))


@dataclass(frozen=True, slots=True)
class CacheEntry:
    url: str
    headers: dict[str, str]
    fetched_at: datetime
    body: bytes

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified")


class Cache:
    """Raw responses on disk, keyed by the full request URL (query string included)."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory if directory is not None else default_cache_dir()

    def _paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        folder = self.directory / digest[:2]
        return folder / f"{digest}.json", folder / f"{digest}.bin"

    def load(self, url: str) -> CacheEntry | None:
        meta_path, body_path = self._paths(url)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
            return CacheEntry(
                url=str(meta["url"]),
                headers={str(k): str(v) for k, v in meta["headers"].items()},
                fetched_at=datetime.fromisoformat(meta["fetched_at"]),
                body=body,
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def store(self, url: str, body: bytes, headers: httpx.Headers, fetched_at: datetime) -> None:
        """Save a response. Failing to write is never an error: the cache is an optimization."""
        if len(body) > MAX_BODY_BYTES:
            return
        meta_path, body_path = self._paths(url)
        meta = {
            "url": url,
            "headers": {k: headers[k] for k in _KEPT_HEADERS if k in headers},
            "fetched_at": fetched_at.astimezone(UTC).isoformat(),
        }
        try:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            self._write(body_path, body)
            self._write(meta_path, json.dumps(meta).encode("utf-8"))
        except OSError:
            return

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as temp:
                temp.write(data)
            os.replace(temp_name, path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise

    def prune(self, max_age: timedelta, now: datetime) -> int:
        """Delete entries not refreshed within `max_age`. Returns how many were removed."""
        removed = 0
        try:
            metas = list(self.directory.glob("*/*.json"))
        except OSError:
            return 0
        for meta_path in metas:
            try:
                fetched = datetime.fromisoformat(json.loads(meta_path.read_text(encoding="utf-8"))["fetched_at"])
            except (OSError, ValueError, KeyError, TypeError):
                fetched = None
            if fetched is not None and now - fetched <= max_age:
                continue
            for path in (meta_path, meta_path.with_suffix(".bin")):
                with contextlib.suppress(OSError):
                    path.unlink()
            removed += 1
        return removed


@dataclass(slots=True)
class StaleMarker:
    """Set by the transport when it answers from the cache because the network failed."""

    hit: bool = False
    urls: list[str] = field(default_factory=list)


_marker: ContextVar[StaleMarker | None] = ContextVar("eyewall_stale_marker", default=None)


@contextlib.contextmanager
def watch_stale() -> Iterator[StaleMarker]:
    """Collect the cache fallbacks of every request made inside the block, including from tasks it starts."""
    marker = StaleMarker()
    token = _marker.set(marker)
    try:
        yield marker
    finally:
        _marker.reset(token)


class CachingTransport(httpx.AsyncBaseTransport):
    """Wraps another transport (the real one unless a test supplies its own) with the disk cache."""

    def __init__(self, cache: Cache, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.cache = cache
        self._inner = inner if inner is not None else httpx.AsyncHTTPTransport()

    async def aclose(self) -> None:
        await self._inner.aclose()

    @staticmethod
    def _from_cache(request: httpx.Request, entry: CacheEntry) -> httpx.Response:
        headers = [(k, v) for k, v in entry.headers.items() if k != "content-length"]
        return httpx.Response(200, headers=headers, stream=httpx.ByteStream(entry.body), request=request)

    def _stale(self, request: httpx.Request, entry: CacheEntry) -> httpx.Response:
        marker = _marker.get()
        if marker is not None:
            marker.hit = True
            marker.urls.append(str(request.url))
        return self._from_cache(request, entry)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return await self._inner.handle_async_request(request)
        url = str(request.url)
        entry = self.cache.load(url)
        conditional = entry is not None and "if-none-match" not in request.headers
        if entry is not None and conditional:
            if entry.etag:
                request.headers["If-None-Match"] = entry.etag
            if entry.last_modified and "if-modified-since" not in request.headers:
                request.headers["If-Modified-Since"] = entry.last_modified
        try:
            response = await self._inner.handle_async_request(request)
        except httpx.TransportError:
            if entry is None:
                raise
            return self._stale(request, entry)
        status = response.status_code
        if status == 304 and entry is not None and conditional:
            await response.aclose()
            return self._from_cache(request, entry)
        if 200 <= status < 300:
            raw = b"".join([chunk async for chunk in response.stream])  # type: ignore[union-attr]
            await response.aclose()
            self.cache.store(url, raw, response.headers, datetime.now(UTC))
            headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() != "content-length"]
            return httpx.Response(status, headers=headers, stream=httpx.ByteStream(raw), request=request)
        if status in _FAILURE_STATUSES and entry is not None:
            await response.aclose()
            return self._stale(request, entry)
        return response
