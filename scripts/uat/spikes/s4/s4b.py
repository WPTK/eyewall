"""S4b: click calibration (3 geometry models, grid, 20 runs), pixel boundary sweep, gesture table.

Usage: s4b.py TERMINAL [RUNS]     TERMINAL = Terminal | iTerm2
Env: OUT, S4. Needs pyobjc Quartz. Writes $OUT/s4b_result.json, s4b_gestures.json, screenshots.
"""

import json
import os
import re
import subprocess
import sys
import time

import Quartz

OUT = os.environ["OUT"]
S4 = os.environ["S4"]
PY = sys.executable
TERM = sys.argv[1]
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 20
APP = {"Terminal": "Terminal", "iTerm2": "iTerm"}[TERM]
OWNER = {"Terminal": "Terminal", "iTerm2": "iTerm2"}[TERM]
RAW = os.path.join(OUT, "raw2.jsonl")
NL = chr(10)
SGR = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
RES = {"terminal": TERM}


def sh(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return 99, repr(e)


def osa(s):
    return sh(["osascript", "-e", s])


def save():
    with open(os.path.join(OUT, "s4b_result.json"), "w") as f:
        json.dump(RES, f, indent=1, default=str)


def events():
    out = []
    try:
        for line in open(RAW):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def window():
    best = None
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        if w.get("kCGWindowOwnerName") == OWNER and w.get("kCGWindowLayer") == 0:
            b = w["kCGWindowBounds"]
            a = b["Width"] * b["Height"]
            if a > 20000 and (best is None or a > best[0]):
                best = (a, int(w["kCGWindowNumber"]), (b["X"], b["Y"], b["Width"], b["Height"]))
    return best[1:] if best else (None, None)


def activate():
    osa('tell application "' + APP + '" to activate')
    time.sleep(0.5)


def post(ev):
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def mouse(kind, x, y, button=Quartz.kCGMouseButtonLeft, flags=0):
    ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), button)
    if flags:
        Quartz.CGEventSetFlags(ev, flags)
    post(ev)


def click(x, y, button="left", flags=0):
    k = {
        "left": (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft),
        "right": (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight),
        "middle": (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter),
    }[button]
    mouse(Quartz.kCGEventMouseMoved, x, y)
    time.sleep(0.05)
    mouse(k[0], x, y, k[2], flags)
    time.sleep(0.04)
    mouse(k[1], x, y, k[2], flags)


def key_escape():
    for d in (True, False):
        post(Quartz.CGEventCreateKeyboardEvent(None, 53, d))
        time.sleep(0.03)


def mark():
    return len(events())


def new_bytes(m, wait=0.8):
    """bytes received since mark m; returns once an SGR release arrived (or timeout)."""
    end = time.time() + wait
    data = b""
    while time.time() < end:
        data = b"".join(bytes.fromhex(e["hex"]) for e in events()[m:] if "hex" in e)
        t = SGR.findall(data)
        if t and t[-1][3] == b"m":
            time.sleep(0.03)
            return b"".join(bytes.fromhex(e["hex"]) for e in events()[m:] if "hex" in e)
        time.sleep(0.03)
    return data


def received_cell(m):
    d = new_bytes(m)
    p = [t for t in SGR.findall(d) if t[3] == b"M"]
    return (int(p[0][1]) - 1, int(p[0][2]) - 1) if p else None


def launch():
    sh("pkill -x Terminal; pkill -x iTerm2; true")
    time.sleep(1.5)
    if os.path.exists(RAW):
        os.remove(RAW)
    inner = os.path.join(OUT, "inner_b.sh")
    with open(inner, "w") as f:
        f.write("#!/bin/bash" + NL + 'export S4_RAW="' + RAW + '" TERM=xterm-256color' + NL + 'exec "' + PY + '" "' + S4 + '/raw2.py"' + NL)
    os.chmod(inner, 0o755)
    if TERM == "Terminal":
        script = NL.join(['tell application "Terminal"', "activate", 'do script "' + inner + '"',
                          "set bounds of front window to {40, 60, 900, 660}", "end tell"])
    else:
        sh("open -a iTerm")
        time.sleep(6)
        script = NL.join(['tell application id "com.googlecode.iterm2"', "activate",
                          "if (count of windows) is 0 then create window with default profile",
                          'tell current session of current window to write text "exec /bin/bash ' + inner + '"',
                          "set bounds of current window to {40, 60, 900, 660}", "end tell"])
    rc, o = sh(["osascript", "-e", script], timeout=40)
    RES["launch"] = {"rc": rc, "out": o}
    end = time.time() + 40
    while time.time() < end and not [e for e in events() if e.get("event") == "ready"]:
        time.sleep(0.4)
    # settle
    last, st = None, 0
    for _ in range(30):
        sz = [e for e in events() if "cols" in e][-1]
        cur = (sz["cols"], sz["rows"], window()[1])
        st = st + 1 if cur == last else 0
        last = cur
        if st >= 6:
            break
        time.sleep(0.5)
    activate()
    sz = [e for e in events() if "cols" in e][-1]
    return sz["cols"], sz["rows"]


def ax_rect():
    """content rect from Accessibility: text area of the terminal window (points)."""
    paths = [
        "scroll area 1 of splitter group 1 of window 1",
        "scroll area 1 of splitter group 1 of group 1 of window 1",
    ]
    for p in paths:
        rc, o = osa('tell application "System Events" to tell process "' + OWNER + '" to get {position, size} of ' + p)
        nums = re.findall(r"-?\d+", o)
        if rc == 0 and len(nums) == 4:
            return p, [float(n) for n in nums]
    return None, None


class Model:
    def __init__(self, name, x0, y0, cw, ch):
        self.name, self.x0, self.y0, self.cw, self.ch = name, x0, y0, cw, ch

    def px(self, c, r):
        return self.x0 + (c + 0.5) * self.cw, self.y0 + (r + 0.5) * self.ch


def cell_at(x, y):
    m = mark()
    click(x, y)
    return received_cell(m)


def find_boundary(axis, fixed, lo, hi, k):
    """smallest pixel along axis where the received cell index becomes >= k (monotone), binary search over [lo,hi]."""
    cache = {}

    def f(p):
        if p not in cache:
            c = cell_at(p, fixed) if axis == "x" else cell_at(fixed, p)
            cache[p] = None if c is None else (c[0] if axis == "x" else c[1])
        return cache[p]

    lo, hi = int(lo), int(hi)
    steps = 0
    while hi - lo > 1 and steps < 12:
        mid = (lo + hi) // 2
        v = f(mid)
        if v is None:
            return None
        if v >= k:
            hi = mid
        else:
            lo = mid
        steps += 1
    return hi


def main():
    cols, rows = launch()
    RES["cols"], RES["rows"] = cols, rows
    wid, b = window()
    RES["window"] = {"id": wid, "bounds": b}
    disp = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    RES["display_points"] = [disp.size.width, disp.size.height]
    sh('screencapture -x "' + OUT + '/b_full.png"')
    rc, o = sh('sips -g pixelWidth "' + OUT + '/b_full.png"')
    m = re.search(r"pixelWidth: (\d+)", o)
    RES["screenshot_px_width"] = int(m.group(1)) if m else None
    RES["backing_scale"] = (int(m.group(1)) / disp.size.width) if m else None
    x, y, w, h = b
    naive = Model("naive_title28", x, y + 28.0, w / cols, (h - 28.0) / rows)
    path, ar = ax_rect()
    RES["ax_path"], RES["ax_rect"] = path, ar
    models = [naive]
    if ar:
        models.append(Model("ax_scrollarea", ar[0], ar[1], ar[2] / cols, ar[3] / rows))
    # ---- pixel boundary sweep (ground truth) ----
    mid_r = rows // 2
    mid_c = cols // 2
    rowy = naive.y0 + (mid_r + 0.5) * naive.ch
    colx = naive.x0 + (mid_c + 0.5) * naive.cw
    def sweep(axis, fixed, o0, size0, n):
        """find boundaries for cell 1, n//2, n-2 (or n-1 for rows) refining the cell size estimate as we go."""
        ks = [1, n // 2, (n - 2) if axis == "x" else (n - 1)]
        out = {}
        est = size0
        first = None
        for k in ks:
            g = o0 + k * est if first is None else first[1] + (k - first[0]) * est
            out[k] = find_boundary(axis, fixed, g - 16 if first is None else g - 8, g + 16 if first is None else g + 8, k)
            if out[k] is None:
                return out
            if first is None:
                first = (k, out[k])
            else:
                est = (out[k] - first[1]) / (k - first[0])
        return out

    xs = sweep("x", rowy, naive.x0, naive.cw, cols)
    ys = sweep("y", colx, naive.y0, naive.ch, rows)
    RES["sweep_x_boundaries"], RES["sweep_y_boundaries"] = xs, ys
    save()
    if None in xs.values() or None in ys.values():
        RES["sweep_failed"] = True
        save()
        gestures(naive, cols, rows)
        return
    ks = sorted(xs)
    cw = (xs[ks[-1]] - xs[ks[0]]) / (ks[-1] - ks[0])
    x0 = xs[ks[0]] - ks[0] * cw
    ks = sorted(ys)
    ch = (ys[ks[-1]] - ys[ks[0]]) / (ks[-1] - ks[0])
    y0 = ys[ks[0]] - ks[0] * ch
    RES["fit"] = {"x0": x0, "y0": y0, "cw": cw, "ch": ch,
                  "x0_minus_window_x": x0 - x, "y0_minus_window_y": y0 - y,
                  "content_right_gap_incl_scrollbar": (x + w) - (x0 + cols * cw), "content_bottom_gap": (y + h) - (y0 + rows * ch)}
    # integer-boundary resolution means true boundary is within [b-1, b]; use b - 0.5 offset on the fit origin
    fit = Model("fit_sweep", x0 - 0.5, y0 - 0.5, cw, ch)
    models.append(fit)
    save()
    # ---- grid ----
    tcols = sorted({0, 1, cols // 4, cols // 2, (3 * cols) // 4, cols - 2, cols - 1})
    trows = sorted({0, rows // 2, rows - 1})
    RES["target_cols"], RES["target_rows"] = tcols, trows
    stats = {mo.name: {"clicks": 0, "miss": 0, "none": 0, "dx": [], "dy": [], "by_cell": {}} for mo in models}
    for run in range(RUNS):
        for r in trows:
            for c in tcols:
                for mo in models:
                    px_, py_ = mo.px(c, r)
                    got = cell_at(px_, py_)
                    s = stats[mo.name]
                    s["clicks"] += 1
                    if got is None:
                        s["none"] += 1
                        s["miss"] += 1
                        continue
                    if got != (c, r):
                        s["miss"] += 1
                        key = "%d,%d" % (c, r)
                        s["by_cell"].setdefault(key, []).append([got[0] - c, got[1] - r])
                    fx, fy = fit.px(c, r)
                    s["dx"].append(px_ - fx)
                    s["dy"].append(py_ - fy)
        for mo in models:
            RES.setdefault("grid", {})[mo.name] = {
                "runs_done": run + 1, "clicks": stats[mo.name]["clicks"], "miss": stats[mo.name]["miss"],
                "none": stats[mo.name]["none"],
                "miss_rate": stats[mo.name]["miss"] / max(1, stats[mo.name]["clicks"]),
                "mean_px_offset_vs_fit_center": [sum(stats[mo.name]["dx"]) / max(1, len(stats[mo.name]["dx"])),
                                                 sum(stats[mo.name]["dy"]) / max(1, len(stats[mo.name]["dy"]))],
                "misses_by_cell(dcol,drow)": stats[mo.name]["by_cell"],
            }
        save()
    # ---- gestures with fit model ----
    gestures(fit, cols, rows)
    sh('screencapture -x -o -l %s "%s/b_window_end.png"' % (wid, OUT))


def decode(d):
    return [(int(a), int(b_), int(c), m.decode()) for a, b_, c, m in SGR.findall(d)]


def gestures(fit, cols, rows):
    G = {}
    cx, cy = fit.px(cols // 3, rows // 3)
    ex, ey = fit.px(cols // 3 + 6, rows // 3 + 3)

    def rec(name, fn, settle=0.8):
        activate()
        m = mark()
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            G[name] = {"error": repr(e)}
            return
        time.sleep(settle)
        d = b"".join(bytes.fromhex(e["hex"]) for e in events()[m:] if "hex" in e)
        G[name] = {"sgr": decode(d), "raw": repr(d)}
        key_escape()  # dismiss any context menu
        time.sleep(0.4)
        sh('screencapture -x -o -l %s "%s/g_%s.png"' % (window()[0], OUT, name))

    rec("left_click", lambda: click(cx, cy))
    rec("right_click", lambda: click(cx, cy, "right"))
    rec("middle_click", lambda: click(cx, cy, "middle"))

    def drag():
        mouse(Quartz.kCGEventMouseMoved, cx, cy)
        time.sleep(0.1)
        mouse(Quartz.kCGEventLeftMouseDown, cx, cy)
        time.sleep(0.1)
        n = 12
        for i in range(1, n + 1):
            mouse(Quartz.kCGEventLeftMouseDragged, cx + (ex - cx) * i / n, cy + (ey - cy) * i / n)
            time.sleep(0.05)
        mouse(Quartz.kCGEventLeftMouseUp, ex, ey)

    rec("drag_left_6cols_3rows", drag)

    def scroll(n):
        def f():
            mouse(Quartz.kCGEventMouseMoved, cx, cy)
            time.sleep(0.1)
            for _ in range(3):
                post(Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, n))
                time.sleep(0.15)
        return f

    rec("scroll_up", scroll(3))
    rec("scroll_down", scroll(-3))
    mods = {"shift": Quartz.kCGEventFlagMaskShift, "ctrl": Quartz.kCGEventFlagMaskControl,
            "alt": Quartz.kCGEventFlagMaskAlternate, "cmd": Quartz.kCGEventFlagMaskCommand}
    for nm, fl in mods.items():
        rec("left_click_" + nm, lambda fl=fl: click(cx, cy, "left", fl))
    rec("right_click_shift", lambda: click(cx, cy, "right", Quartz.kCGEventFlagMaskShift))
    RES["gesture_note"] = "sgr tuples: (cb, col1based, row1based, M=press/drag m=release); cb bit 4=shift 8=alt 16=ctrl 32=motion; 64/65=wheel up/down"
    with open(os.path.join(OUT, "s4b_gestures.json"), "w") as f:
        json.dump(G, f, indent=1)
    RES["gestures"] = G
    save()


try:
    main()
finally:
    save()
