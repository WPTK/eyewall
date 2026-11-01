#!/bin/bash
# S4b job: $1 = Terminal|iTerm2, $2 = std|hidpi
. "$(dirname "$0")/common.sh"
TERMN="$1"; VARIANT="$2"
export S4PY="$HOME/s4venv/bin/python"
for i in 1 2 3; do
  bash "$S4/grant.sh" > "$OUT/grant$i.txt" 2>&1
  sleep 3
  if osascript -e 'tell application "System Events" to key code 0' >> "$OUT/ax_preflight.txt" 2>&1; then echo "AX preflight ok on try $i" >> "$OUT/ax_preflight.txt"; break; fi
  echo "AX preflight FAILED on try $i" >> "$OUT/ax_preflight.txt"
done
cat "$OUT/ax_preflight.txt"
if [ "$TERMN" = "iTerm2" ]; then
  defaults write com.googlecode.iterm2 EnableAPIServer -bool true
  defaults write com.googlecode.iterm2 SUEnableAutomaticChecks -bool false
  defaults write com.googlecode.iterm2 SUHasLaunchedBefore -bool true
  defaults write com.googlecode.iterm2 SUSendProfileInfo -bool false
  defaults write com.googlecode.iterm2 NoSyncTipsDisabled -bool true
  open -a iTerm; sleep 8
  "$S4PY" "$S4/dismiss.py" 1 > "$OUT/dismiss1.txt" 2>&1
fi
if [ "$VARIANT" = "hidpi" ]; then
  "$S4PY" "$S4/hidpi.py" > "$OUT/hidpi.txt" 2>&1; echo "hidpi exit $?" >> "$OUT/hidpi.txt"; tail -25 "$OUT/hidpi.txt"
  sleep 5
fi
mkdir -p "$OUT/func" "$OUT/cal"
if [ "$VARIANT" = "std" ]; then
  OUT="$OUT/func" "$S4PY" "$S4/drive.py" "$TERMN" osa,cgevent,cliclick 2>&1 | tee "$OUT/func/drive.log"
fi
OUT="$OUT/cal" "$S4PY" "$S4/s4b.py" "$TERMN" "${RUNS:-20}" 2>&1 | tee "$OUT/cal/s4b.log"
if [ "$TERMN" = "iTerm2" ] && [ "$VARIANT" = "std" ]; then
  mkdir -p "$OUT/lnet"
  OUT="$OUT/lnet" "$S4PY" "$S4/lnet.py" 2>&1 | tee "$OUT/lnet/lnet.log"
fi
