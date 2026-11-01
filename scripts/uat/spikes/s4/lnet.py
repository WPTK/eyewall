"""Force the macOS 'find devices on local networks' prompt for iTerm2 and verify dismiss.py clicks it.

Runs a local-network probe inside an iTerm2 session (launch via write text), screenshots, runs dismiss.py, screenshots.
"""

import os
import subprocess
import sys
import time

import Quartz

OUT = os.environ["OUT"]
S4 = os.environ["S4"]
NL = chr(10)


def sh(c, t=60):
    p = subprocess.run(c, shell=isinstance(c, str), capture_output=True, text=True, timeout=t)
    return p.returncode, (p.stdout + p.stderr).strip()


def owners():
    out = []
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        out.append((w.get("kCGWindowOwnerName"), w.get("kCGWindowName"), w.get("kCGWindowLayer")))
    return out


sh("pkill -x iTerm2; true")
time.sleep(1.5)
sh("open -a iTerm")
time.sleep(6)
probe = os.path.join(OUT, "lnet_probe.sh")
with open(probe, "w") as f:
    f.write("#!/bin/bash" + NL +
            "python3 - <<'EOF'" + NL +
            "import socket" + NL +
            "for ip in ('192.168.1.1','192.168.0.1','10.0.0.1','172.16.0.1','224.0.0.251'):" + NL +
            "    s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM if ip.startswith('224') else socket.SOCK_STREAM); s.settimeout(1.5)" + NL +
            "    try:" + NL +
            "        s.connect((ip,5353 if ip.startswith('224') else 80)); s.send(b'x')" + NL +
            "    except Exception as e:" + NL +
            "        print(ip, e)" + NL +
            "EOF" + NL +
            "dns-sd -B _services._dns-sd._udp local. & sleep 4; kill $!" + NL + "sleep 120" + NL)
os.chmod(probe, 0o755)
script = NL.join(['tell application id "com.googlecode.iterm2"', "activate",
                  "if (count of windows) is 0 then create window with default profile",
                  'tell current session of current window to write text "/bin/bash ' + probe + '"', "end tell"])
print(sh(["osascript", "-e", script]))
dialog = False
for i in range(12):
    time.sleep(2)
    ow = owners()
    cand = [o for o in ow if o[0] in ("UserNotificationCenter", "CoreServicesUIAgent", "SecurityAgent") or (o[1] and "local network" in str(o[1]).lower())]
    if cand:
        dialog = True
        print("dialog window seen after", (i + 1) * 2, "s:", cand)
        break
sh('screencapture -x "' + OUT + '/lnet_before_dismiss.png"')
rc, o = sh([sys.executable, S4 + "/dismiss.py", "2"], 180)
print(o)
sh('screencapture -x "' + OUT + '/lnet_after_dismiss.png"')
clicked = "dismissed 0" not in o
print("RESULT dialog_seen=%s dismissed_by_script=%s owners_after=%s" % (dialog, clicked, [x for x in owners() if x[0] in ("UserNotificationCenter", "CoreServicesUIAgent")]))
