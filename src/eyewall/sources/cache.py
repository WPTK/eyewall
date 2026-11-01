"""A disk cache of raw responses, so a launch paints instantly and an offline launch shows the last data.

The cache sits under the HTTP client as a transport (`CachingTransport`), which makes it work for every feed without
the parsers knowing about it:

- A GET whose URL is cached is sent with the saved `ETag` / `Last-Modified` as validators. A 304 comes back to the
  caller as the cached 200, so a feed that has not changed costs a header exchange and no body.
- A 2xx answer replaces the cached copy.
- When the network fails (no connection, a timeout, a loss during the body) or the server answers 429 or 5xx, and a
  copy exists, the caller gets the copy and the current `StaleMarker` is set, so the live source can say the feed is
  stale. A 429 or 5xx also records the status and the server's Retry-After on the marker, so the poller can back off.
  With no copy the failure propagates as usual.
- The disk is touched from a worker thread, one await at a time, so the UI loop never waits on it. The body file is
  read only when it is used: after a 304 or when serving a copy.

Entries live under `platformdirs.user_cache_dir("eyewall")` as a `.json` metadata file and a `.bin` raw body (still
compressed if the server compressed it, so the client decodes it the same way as a fresh answer).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from platformdirs import user_cache_dir

from eyewall.net import MAX_BYTES_EXTENSION, FetchError, HttpError, RateLimited, retry_after_seconds

log = logging.getLogger(__name__)
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

    def load(self, url: str, *, with_body: bool = True) -> CacheEntry | None:
        """The cached answer for a URL. Without `with_body` the body file is only checked for, not read (`body` is
        empty); `read_body` fetches it when it is needed."""
        meta_path, body_path = self._paths(url)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if with_body:
                body = body_path.read_bytes()
            elif body_path.is_file():
                body = b""
            else:
                return None
            return CacheEntry(
                url=str(meta["url"]),
                headers={str(k): str(v) for k, v in meta["headers"].items()},
                fetched_at=datetime.fromisoformat(meta["fetched_at"]),
                body=body,
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def read_body(self, url: str) -> bytes | None:
        """The cached body, or None when the file is gone."""
        try:
            return self._paths(url)[1].read_bytes()
        except OSError:
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

    def touch(self, url: str, fetched_at: datetime) -> None:
        """Record that the entry was just validated (a 304), so `prune` does not age out a page that rarely changes."""
        meta_path, _ = self._paths(url)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["fetched_at"] = fetched_at.astimezone(UTC).isoformat()
            self._write(meta_path, json.dumps(meta).encode("utf-8"))
        except (OSError, ValueError, TypeError, AttributeError):
            return

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
        try:  # a body whose metadata file is gone (a write cut short, a half-deleted entry) is never read again
            for body_path in self.directory.glob("*/*.bin"):
                if not body_path.with_suffix(".json").exists():
                    with contextlib.suppress(OSError):
                        body_path.unlink()
                    removed += 1
        except OSError:
            pass
        return removed


@dataclass(slots=True)
class StaleMarker:
    """Set by the transport when it answers from the cache because the network failed."""

    hit: bool = False
    urls: list[str] = field(default_factory=list)
    failure: FetchError | None = None  # the first 429 or 5xx the cache answered for
    retry_after: float | None = None  # the longest Retry-After any of them carried


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


class _Overflow(httpx.AsyncByteStream):
    """A body too big to cache: the chunks already read, then the rest of the live stream, never held whole here."""

    def __init__(self, head: list[bytes], rest: AsyncIterator[bytes], response: httpx.Response) -> None:
        self._head = head
        self._rest = rest
        self._response = response

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._head:
            yield chunk
        async for chunk in self._rest:
            yield chunk

    async def aclose(self) -> None:
        await self._response.aclose()


class EnvTransport(httpx.AsyncBaseTransport):
    """The network, reached the way httpx reaches it for a client with no custom transport: through the proxies named
    by HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and NO_PROXY, and on Windows and macOS the system proxy setting (httpx reads
    both through `urllib.request.getproxies`). A client given a transport of its own ignores them (httpx only reads the
    environment when it builds the transport itself), so the proxy routing lives in this inner client. A proxy address
    httpx cannot use (an unknown scheme, a malformed port, or socks without the socksio package) is logged and skipped:
    the requests go direct instead of the app failing to start. Redirects are left to the outer client."""

    def __init__(self) -> None:
        try:
            self._client = httpx.AsyncClient(trust_env=True, follow_redirects=False)
        except (ValueError, ImportError, httpx.InvalidURL) as exc:
            log.warning("ignoring the configured proxy, requests go direct (%s)", type(exc).__name__)
            self._client = httpx.AsyncClient(trust_env=False, follow_redirects=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._client.send(request, stream=True)

    async def aclose(self) -> None:
        await self._client.aclose()


class CachingTransport(httpx.AsyncBaseTransport):
    """Wraps another transport (the real one unless a test supplies its own) with the disk cache."""

    def __init__(self, cache: Cache, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.cache = cache
        self._inner = inner if inner is not None else EnvTransport()

    async def aclose(self) -> None:
        await self._inner.aclose()

    @staticmethod
    def _from_cache(request: httpx.Request, entry: CacheEntry) -> httpx.Response:
        headers = [(k, v) for k, v in entry.headers.items() if k != "content-length"]
        headers.append(("content-length", str(len(entry.body))))  # of the stored (still compressed) bytes
        return httpx.Response(200, headers=headers, stream=httpx.ByteStream(entry.body), request=request)

    async def _stale(
        self, request: httpx.Request, entry: CacheEntry, failure: httpx.Response | None = None
    ) -> httpx.Response | None:
        """The cached copy as the answer, noting on the marker why; None when the body file is gone. `failure` is the
        server's 429 or 5xx, which the poller treats as a failure (it backs off) even though the copy is served."""
        body = await asyncio.to_thread(self.cache.read_body, str(request.url))
        if body is None:
            return None
        marker = _marker.get()
        if marker is not None:
            marker.hit = True
            marker.urls.append(str(request.url))
            if failure is not None:
                after = retry_after_seconds(failure)
                if marker.failure is None:
                    url = str(request.url)
                    marker.failure = (
                        RateLimited(url, after) if failure.status_code == 429 else HttpError(url, failure.status_code)
                    )
                if after is not None:
                    marker.retry_after = max(after, marker.retry_after or 0.0)
        return self._from_cache(request, replace(entry, body=body))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return await self._inner.handle_async_request(request)
        url = str(request.url)
        entry = await asyncio.to_thread(self.cache.load, url, with_body=False)
        conditional = entry is not None and "if-none-match" not in request.headers
        if entry is not None and conditional:
            if entry.etag:
                request.headers["If-None-Match"] = entry.etag
            if entry.last_modified and "if-modified-since" not in request.headers:
                request.headers["If-Modified-Since"] = entry.last_modified
        try:
            response = await self._inner.handle_async_request(request)
        except httpx.TransportError:
            served = None if entry is None else await self._stale(request, entry)
            if served is None:
                raise
            return served
        status = response.status_code
        if status == 304 and entry is not None and conditional:
            await response.aclose()
            body = await asyncio.to_thread(self.cache.read_body, url)
            if body is not None:
                await asyncio.to_thread(self.cache.touch, url, datetime.now(UTC))
                return self._from_cache(request, replace(entry, body=body))
            # The body file is gone: ask again without validators, as for a URL that was never cached.
            entry = None
            request.headers.pop("If-None-Match", None)
            request.headers.pop("If-Modified-Since", None)
            response = await self._inner.handle_async_request(request)
            status = response.status_code
        if 200 <= status < 300:
            limit = min(MAX_BODY_BYTES, int(request.extensions.get(MAX_BYTES_EXTENSION) or MAX_BODY_BYTES))
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit:
                return response  # too big to cache or for this caller: pass it on untouched, nothing is read here
            try:
                return await self._cache_or_pass(request, response, url, limit)
            except httpx.TransportError:  # lost during the body: the copy answers
                await response.aclose()
                served = None if entry is None else await self._stale(request, entry)
                if served is None:
                    raise
                return served
        if status in _FAILURE_STATUSES and entry is not None:
            served = await self._stale(request, entry, response)
            if served is not None:
                await response.aclose()
                return served
        return response

    async def _cache_or_pass(
        self, request: httpx.Request, response: httpx.Response, url: str, limit: int
    ) -> httpx.Response:
        """Read a 2xx body into the cache, unless it passes `limit` (no declared length, then too much arrived): hand
        it on as a stream, uncached, so the transport never holds more than the limit and the caller decides."""
        stream = response.stream.__aiter__()  # type: ignore[union-attr]
        chunks: list[bytes] = []
        size = 0
        async for chunk in stream:
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                return httpx.Response(
                    response.status_code,
                    headers=response.headers.multi_items(),
                    stream=_Overflow(chunks, stream, response),
                    request=request,
                )
        await response.aclose()
        raw = b"".join(chunks)
        await asyncio.to_thread(self.cache.store, url, raw, response.headers, datetime.now(UTC))
        headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() != "content-length"]
        headers.append(("content-length", str(len(raw))))
        return httpx.Response(response.status_code, headers=headers, stream=httpx.ByteStream(raw), request=request)
