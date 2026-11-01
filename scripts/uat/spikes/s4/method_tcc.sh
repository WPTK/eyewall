#!/bin/bash
# Attempt 2: grant TCC via sudo, then drive Terminal.app with osascript / CGEvent / cliclick
. "$(dirname "$0")/common.sh"
export S4PY="$HOME/s4venv/bin/python"
bash "$S4/grant.sh" > "$OUT/grant.txt" 2>&1; tail -5 "$OUT/grant.txt"
"$S4PY" "$S4/drive.py" Terminal osa,cgevent,cliclick 2>&1 | tee "$OUT/drive.log"
