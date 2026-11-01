#!/bin/bash
# Attempt 4: iTerm2 with Python API enabled; real input via TCC-granted CGEvent / cliclick / osascript
. "$(dirname "$0")/common.sh"
export S4PY="$HOME/s4venv/bin/python"
bash "$S4/grant.sh" > "$OUT/grant.txt" 2>&1; tail -3 "$OUT/grant.txt"
defaults write com.googlecode.iterm2 EnableAPIServer -bool true
defaults write com.googlecode.iterm2 NoSyncDoNotWarnBeforeMultilinePaste -bool true
defaults write com.googlecode.iterm2 "NoSyncPermissionToShowTip" -bool false
open -a iTerm; sleep 8
defaults read com.googlecode.iterm2 > "$OUT/iterm_defaults.txt" 2>&1
strings -a /Applications/iTerm.app/Contents/MacOS/iTerm2 | grep -i -E 'authentic|APIAuth|cookie|NoSync.*API|API.*Permission' | sort -u | head -60 > "$OUT/iterm_strings.txt"
lsof -nP -U 2>/dev/null | grep -i iterm | head -5 > "$OUT/iterm_sockets.txt"
"$S4PY" "$S4/drive.py" iTerm2 cgevent,cliclick,osa 2>&1 | tee "$OUT/drive.log"
