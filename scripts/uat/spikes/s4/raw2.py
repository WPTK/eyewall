"""Raw reader for S4b: mouse tracking 1000+1002+1006, logs every byte chunk to $S4_RAW with a timestamp. Exits on 'q' or after 900 s."""

import json
import os
import select
import signal
import sys
import termios
import time
import tty

RAW = os.environ.get("S4_RAW", "/tmp/s4_raw2.jsonl")


def w(d):
    with open(RAW, "a") as f:
        f.write(json.dumps({"t": time.time(), **d}) + "\n")


fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setraw(fd)
sys.stdout.write("\x1b[2J\x1b[H\x1b[?1000h\x1b[?1002h\x1b[?1006h")
sys.stdout.write("RAW2 reader\r\n")
sys.stdout.flush()


def size(event):
    c, r = os.get_terminal_size()
    w({"event": event, "cols": c, "rows": r})


size("ready")
signal.signal(signal.SIGWINCH, lambda *_a: size("resize"))
end = time.time() + 900
try:
    while time.time() < end:
        if select.select([fd], [], [], 0.2)[0]:
            d = os.read(fd, 512)
            w({"hex": d.hex()})
            if d == b"q":
                break
finally:
    sys.stdout.write("\x1b[?1006l\x1b[?1002l\x1b[?1000l\x1b[2J\x1b[H")
    sys.stdout.flush()
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
    w({"event": "done"})
