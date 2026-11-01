"""Try to put the runner display into a HiDPI (2x backing) mode. Logs everything; exit 0 if a mode was applied."""

import re
import subprocess
import sys

import Quartz


def sh(c):
    p = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr)


def state(tag):
    d = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    mode = Quartz.CGDisplayCopyDisplayMode(Quartz.CGMainDisplayID())
    print(tag, "points", d.size.width, d.size.height, "pixels",
          Quartz.CGDisplayModeGetPixelWidth(mode), Quartz.CGDisplayModeGetPixelHeight(mode))
    # all modes including HiDPI ones
    opts = {Quartz.kCGDisplayShowDuplicateLowResolutionModes: True}
    modes = Quartz.CGDisplayCopyAllDisplayModes(Quartz.CGMainDisplayID(), opts) or []
    for m in modes:
        print("  mode", Quartz.CGDisplayModeGetWidth(m), "x", Quartz.CGDisplayModeGetHeight(m), "px",
              Quartz.CGDisplayModeGetPixelWidth(m), "x", Quartz.CGDisplayModeGetPixelHeight(m), "hz", Quartz.CGDisplayModeGetRefreshRate(m))
    return modes


modes = state("before")
print(sh("system_profiler SPDisplaysDataType")[1])
hidpi = [m for m in modes if Quartz.CGDisplayModeGetPixelWidth(m) >= 2 * Quartz.CGDisplayModeGetWidth(m)]
print("hidpi modes available:", len(hidpi))
rc, o = sh("brew tap jakehilborn/jakehilborn && brew install displayplacer 2>&1 | tail -3")
print(o)
rc, o = sh("displayplacer list")
print(o)
applied = False
if hidpi:
    m = sorted(hidpi, key=lambda m: -Quartz.CGDisplayModeGetWidth(m))[0]
    err, cfg = Quartz.CGBeginDisplayConfiguration(None)
    err2 = Quartz.CGConfigureDisplayWithDisplayMode(cfg, Quartz.CGMainDisplayID(), m, None)
    err3 = Quartz.CGCompleteDisplayConfiguration(cfg, Quartz.kCGConfigureForSession)
    print("CGConfigure", err, err2, err3)
    applied = err3 == 0
else:
    # displayplacer: pick a mode line with scaling:on
    best = None
    for line in o.splitlines():
        mm = re.match(r"\s*mode (\d+): res:(\d+)x(\d+) hz:(\d+) color_depth:(\d+).*scaling:on", line)
        if mm:
            best = mm
    pid = re.search(r"Persistent screen id: (\S+)", o)
    if best and pid:
        cmd = 'displayplacer "id:%s res:%sx%s hz:%s color_depth:%s scaling:on"' % (pid.group(1), best.group(2), best.group(3), best.group(4), best.group(5))
        print(cmd)
        print(sh(cmd))
        applied = True
modes = state("after")
sys.exit(0 if applied else 1)
