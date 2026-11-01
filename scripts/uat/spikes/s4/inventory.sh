#!/bin/bash
# Attempt 1: what does the image already grant?
. "$(dirname "$0")/common.sh"
{
run sw_vers; run uname -m; run csrutil status; run id; run launchctl managername
run stat -f%Su /dev/console; run who
for db in "/Library/Application Support/com.apple.TCC/TCC.db" "$HOME/Library/Application Support/com.apple.TCC/TCC.db"; do
  echo "== $db"; ls -l "$db"
  run sudo sqlite3 "$db" ".schema access"
  run sudo sqlite3 -header "$db" "select service,client,client_type,auth_value,auth_reason from access where service in ('kTCCServiceAccessibility','kTCCServiceScreenCapture','kTCCServiceAppleEvents','kTCCServicePostEvent','kTCCServiceListenEvent')"
done
echo "== System Events keystroke test"
run osascript -e 'tell application "System Events" to count processes'
run osascript -e 'tell application "System Events" to keystroke "a"'
run osascript -e 'tell application "System Events" to key code 0'
echo "== screen"
run system_profiler SPDisplaysDataType
run screencapture -x "$OUT/inv_screen.png"
run ls -l "$OUT/inv_screen.png"
run ls /Applications
} > "$OUT/inventory.txt" 2>&1
cat "$OUT/inventory.txt"
