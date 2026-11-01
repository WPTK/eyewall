"""A tiny local forward proxy with an on/off switch, to take an app offline and bring it back without restarting it.

Point the app at it with HTTP_PROXY/HTTPS_PROXY. While ``blocked`` is true every request is refused at once (a 503 for
CONNECT, so the app sees a proxy error); when it is false CONNECT tunnels are relayed byte for byte, so TLS stays
end to end and nothing is decrypted. Plain-HTTP absolute-form requests are refused too: the NOAA feeds are all https.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from select import select


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        proxy: Proxy = self.server.proxy  # type: ignore[attr-defined]
        sock: socket.socket = self.request
        sock.settimeout(15)
        try:
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                head += chunk
            first = head.split(b"\r\n", 1)[0].decode("latin-1")
            method, _, rest = first.partition(" ")
            target = rest.rsplit(" ", 1)[0]
            proxy.requests.append(first)
            if proxy.blocked or method != "CONNECT":
                sock.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            host, _, port = target.rpartition(":")
            upstream = socket.create_connection((host, int(port)), timeout=15)
            sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self._relay(sock, upstream, proxy)
        except OSError:
            return

    @staticmethod
    def _relay(a: socket.socket, b: socket.socket, proxy: Proxy) -> None:
        a.settimeout(None)
        b.settimeout(None)
        try:
            while not proxy.blocked:
                ready, _, _ = select([a, b], [], [], 0.5)
                for s in ready:
                    data = s.recv(65536)
                    if not data:
                        return
                    (b if s is a else a).sendall(data)
        finally:
            b.close()


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Proxy:
    def __init__(self, *, blocked: bool = True) -> None:
        self.blocked = blocked
        self.requests: list[str] = []
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.proxy = self  # type: ignore[attr-defined]
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
