# Install

eyewall needs a terminal; a modern one (Windows Terminal, iTerm2, GNOME Terminal, kitty) draws the map best. It reads
free NOAA feeds and needs no account or key. It is not an official warning source: for decisions that matter, use
the National Hurricane Center and your local National Weather Service office.

## A standalone binary

Once a release is published, download the file for your platform from the [releases page](https://github.com/WPTK/eyewall/releases) and run it. No
Python is needed.

| Platform | File |
| --- | --- |
| Windows, x86_64 | `eyewall-windows-x86_64.exe` |
| Linux, x86_64 | `eyewall-linux-x86_64.tar.gz` |
| Linux, arm64 | `eyewall-linux-arm64.tar.gz` |
| macOS, Apple silicon | `eyewall-macos-arm64.tar.gz` |
| macOS, Intel | `eyewall-macos-x86_64.tar.gz` |

Check the download against `SHA256SUMS` from the same release. On Linux and macOS, unpack the archive
(`tar -xzf eyewall-linux-x86_64.tar.gz`); it holds one executable file, `eyewall`, with the executable bit set, so there
is no `chmod`. The binaries are not signed; Windows SmartScreen may warn on first run ("More info", then "Run anyway"), and on macOS `xattr -d com.apple.quarantine eyewall` clears the quarantine flag. Then try it:

```
eyewall --demo         # replay the bundled recording of Hurricane Erin (2025)
eyewall                # live data
```

## With Python 3.12 or newer

```
pipx install git+https://github.com/WPTK/eyewall
```

## Checking an installation

`eyewall --selftest` replays an hour of the bundled storm through every parser and draws one map frame. It prints
`selftest ok` and exits 0, or names the failure and exits 1.

## Settings

The first save from the settings screen (`S`, then `Ctrl+S`) creates `config.toml` in the per-user config directory
(`%APPDATA%\eyewall` on Windows, `~/.config/eyewall` on Linux, `~/Library/Application Support/eyewall` on macOS).
`--config PATH` reads another file; `--no-config` ignores the file for one run.
