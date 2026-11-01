#!/bin/bash
. "$(dirname "$0")/common.sh"
method="$1"
python -m venv "$HOME/s4venv"
"$HOME/s4venv/bin/pip" -q install textual pyobjc-framework-Quartz pyobjc-framework-ApplicationServices
brew install cliclick 2>&1 | tail -3
case "$method" in
  vnc)   "$HOME/s4venv/bin/pip" -q install vncdotool ;;
  iterm) brew install --cask iterm2 2>&1 | tail -3; "$HOME/s4venv/bin/pip" -q install iterm2; sudo xattr -dr com.apple.quarantine /Applications/iTerm.app; /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/iTerm.app; mdls -name kMDItemCFBundleIdentifier /Applications/iTerm.app ;;
esac
ls /Applications | tee "$OUT/apps.txt"
