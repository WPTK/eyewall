"""List the RFB security types a VNC server offers on 127.0.0.1:5900 (is legacy VNC password auth, type 2, offered?)."""

import socket

s = socket.create_connection(("127.0.0.1", 5900), timeout=10)
ver = s.recv(12)
print("server version:", ver)
s.sendall(ver)
n = s.recv(1)[0]
if n == 0:
    ln = int.from_bytes(s.recv(4), "big")
    print("server refused:", s.recv(ln))
else:
    types = list(s.recv(n))
    names = {1: "None", 2: "VNC password", 30: "ARD (DH)", 33: "ARD/MSLogon-like", 35: "Apple SRP?", 36: "Apple", 18: "TLS", 19: "VeNCrypt"}
    print("security types offered:", [(t, names.get(t, "?")) for t in types])
