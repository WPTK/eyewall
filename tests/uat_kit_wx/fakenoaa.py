"""A CONNECT proxy that stands in for chosen NOAA hosts, for driving the unmodified eyewall exe.

Per host: ``real`` tunnels to the real server, ``refuse`` answers 502 to the CONNECT, ``origin`` hands the TLS stream to
a local origin (test-CA certificate for every host) that answers from ``routes(host, path) -> (status, ctype, body)``.
``blocked`` refuses every CONNECT with a 503 (the network is cut) and can be flipped while the app runs. The exe honours
HTTPS_PROXY and SSL_CERT_FILE (spike S2b); SSL_CERT_FILE replaces trust, so the bundle is certifi plus the test CA.
Test-only. Needs ``openssl`` on PATH.
"""

from __future__ import annotations

import asyncio
import ssl
import threading
import time
from collections.abc import Callable
from pathlib import Path

import certifi

from .certs import TestCA

NOAA_HOSTS = [
    "www.nhc.noaa.gov",
    "ftp.nhc.noaa.gov",
    "tgftp.nws.noaa.gov",
    "api.weather.gov",
    "www.ndbc.noaa.gov",
    "api.tidesandcurrents.noaa.gov",
    "cdn.star.nesdis.noaa.gov",
]
Route = Callable[[str, str], tuple[int, str, bytes]]


class FakeNoaa:
    def __init__(
        self,
        workdir: Path,
        *,
        modes: dict[str, str] | None = None,
        default: str = "refuse",
        routes: Route | None = None,
    ) -> None:
        self.modes = dict(modes or {})
        self.default = default
        self.routes = routes or (lambda host, path: (404, "text/plain", b"not found"))
        self.blocked = False
        self.log: list[dict[str, object]] = []
        self.ca = TestCA(Path(workdir) / "ca", NOAA_HOSTS)
        self.bundle = Path(workdir) / "bundle.pem"
        self.bundle.write_bytes(Path(certifi.where()).read_bytes() + b"\n" + self.ca.ca_pem.read_bytes())
        self.t0 = time.monotonic()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        if not self._ready.wait(15):
            raise RuntimeError("fake NOAA proxy did not start")

    # -- environment for the child --------------------------------------------------------------------------------
    def env(self) -> dict[str, str]:
        url = f"http://127.0.0.1:{self.port}"
        return {
            "HTTPS_PROXY": url,
            "https_proxy": url,
            "HTTP_PROXY": url,
            "http_proxy": url,
            "NO_PROXY": "",
            "no_proxy": "",
            "SSL_CERT_FILE": str(self.bundle),
        }

    def hits(self, host: str | None = None) -> list[dict[str, object]]:
        return [r for r in self.log if host is None or r.get("host") == host]

    # -- server ---------------------------------------------------------------------------------------------------
    def _serve(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        sctx.load_cert_chain(str(self.ca.leaf_pem), str(self.ca.leaf_key))
        origin = await asyncio.start_server(self._origin, "127.0.0.1", 0, ssl=sctx)
        self._oport = origin.sockets[0].getsockname()[1]
        proxy = await asyncio.start_server(self._proxy, "127.0.0.1", 0)
        self.port: int = proxy.sockets[0].getsockname()[1]
        self._ready.set()
        await self._stop.wait()
        proxy.close()
        origin.close()

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(5)

    def _now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    async def _origin(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while True:  # keep-alive: answer every request on the connection
                head = await r.readuntil(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                path = lines[0].split()[1]
                host = next((ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("host:")), "")
                host = host.split(":")[0]
                status, ctype, body = self.routes(host, path)
                self.log.append({"t": self._now(), "kind": "origin", "host": host, "path": path, "status": status})
                reason = {200: "OK", 404: "Not Found"}.get(status, "Status")
                w.write(
                    f"HTTP/1.1 {status} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n\r\n".encode()
                    + body
                )
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError, OSError):
            pass
        finally:
            w.close()

    @staticmethod
    async def _pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while data := await r.read(65536):
                w.write(data)
                await w.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            w.close()

    async def _proxy(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            head = await r.readuntil(b"\r\n\r\n")
            first = head.split(b"\r\n")[0].decode("latin-1")
            parts = first.split()
            host = parts[1].split(":")[0] if len(parts) > 1 else ""
            mode = self.modes.get(host, self.default)
            entry: dict[str, object] = {"t": self._now(), "kind": "connect", "host": host, "line": first}
            if self.blocked or parts[0] != "CONNECT":
                entry["result"] = "503 blocked"
                self.log.append(entry)
                w.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await w.drain()
                w.close()
                return
            if mode == "refuse":
                entry["result"] = "502 refused"
                self.log.append(entry)
                w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await w.drain()
                w.close()
                return
            entry["result"] = mode
            self.log.append(entry)
            if mode == "origin":
                up_r, up_w = await asyncio.open_connection("127.0.0.1", self._oport)
            else:
                up_r, up_w = await asyncio.open_connection(host, 443)
            w.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await w.drain()
            await asyncio.gather(self._pipe(r, up_w), self._pipe(up_r, w))
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            w.close()
