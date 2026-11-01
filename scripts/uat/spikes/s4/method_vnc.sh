#!/bin/bash
# Attempt 3: loopback VNC via Screen Sharing / ARD kickstart, drive with vncdotool
. "$(dirname "$0")/common.sh"
export S4PY="$HOME/s4venv/bin/python"
PW="$(openssl rand -hex 6)"
bash "$S4/grant.sh" > "$OUT/grant.txt" 2>&1   # only so Terminal can be launched/read via Apple Events; input itself goes through VNC
export PYTHONWARNINGS=ignore
sudo sysadminctl -resetPasswordFor runner -newPassword "$PW" > "$OUT/runnerpw.txt" 2>&1
sudo sysadminctl -addUser vncuser -password "$PW" -admin > "$OUT/adduser.txt" 2>&1
KS=/System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart
{
run sudo "$KS" -activate -configure -access -on -users vncuser -clientopts -setvnclegacy -vnclegacy yes -clientopts -setvncpw -vncpw "$PW" -restart -agent -privs -all
run sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.screensharing.plist
run sudo launchctl list | grep -i -E 'screensharing|ARD'
sleep 5
run nc -vz 127.0.0.1 5900
run lsof -nP -iTCP:5900
} > "$OUT/vnc_enable.txt" 2>&1
cat "$OUT/vnc_enable.txt"
export VNC_SERVER="127.0.0.1::5900" VNC_PW="$PW"
best=0; export VNC_USER=vncuser
for u in vncuser runner; do
  "$HOME/s4venv/bin/vncdo" -s "$VNC_SERVER" -u $u -p "$VNC_PW" capture "$OUT/vnc_capture_$u.png" > "$OUT/vnc_capture_$u.txt" 2>&1
  sz=$(stat -f%z "$OUT/vnc_capture_$u.png" 2>/dev/null || echo 0); echo "capture as $u: $sz bytes"
  if [ "$sz" -gt "$best" ]; then best=$sz; export VNC_USER=$u; fi
done
echo "using VNC user $VNC_USER"
# VNC is the only injection backend here; no TCC grant is written
"$S4PY" "$S4/drive.py" Terminal vnc 2>&1 | tee "$OUT/drive.log"
