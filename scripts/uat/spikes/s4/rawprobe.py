"""Raw reader: enable mouse tracking (1000+1006), log every byte received to $S4_RAW, exit after 2 SGR releases or 25s."""

import json
import os
import select
import sys
import termios
import time
import tty

RAW = os.environ.get("S4_RAW", "/tmp/s4_raw.jsonl")


def w(d: dict) -> None:
    with open(RAW, "a") as f:
        f.write(json.dumps({"t": time.time(), **d}) + "\n")


fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setraw(fd)
cols, rows = os.get_terminal_size()
sys.stdout.write("\x1b[2J\x1b[H\x1b[?1000h\x1b[?1006h")
sys.stdout.write(f"RAWPROBE cols={cols} rows={rows}\r\n")
sys.stdout.flush()
w({"event": "ready", "cols": cols, "rows": rows})
end = time.time() + 25
rel = 0
try:
    while time.time() < end and rel < 2:
        if select.select([fd], [], [], 0.25)[0]:
            d = os.read(fd, 256)
            w({"hex": d.hex(), "repr": repr(d)})
            rel += d.count(b"m")
finally:
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[2J\x1b[H")
    sys.stdout.flush()
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
    w({"event": "done"})
