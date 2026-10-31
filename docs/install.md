# Install

eyewall needs a terminal; a modern one (Windows Terminal, iTerm2, GNOME Terminal, kitty) draws the map best. It reads
free NOAA feeds and needs no account or key. It is not an official warning source: for decisions that matter, use
the National Hurricane Center and your local National Weather Service office.

## A standalone binary

Download the file for your platform from the [releases page](https://github.com/WPTK/eyewall/releases) and run it. No
Python is needed.

| Platform | File |
| --- | --- |
| Windows, x86_64 | `eyewall-windows-x86_64.exe` |
| Linux, x86_64 | `eyewall-linux-x86_64` |
| Linux, arm64 | `eyewall-linux-arm64` |
| macOS, Apple silicon | `eyewall-macos-arm64` |
| macOS, Intel | `eyewall-macos-x86_64` |

Check the download against `SHA256SUMS` from the same release. On Linux and macOS, `chmod +x` the file first. The
binaries are not signed; see `smoke-test.md` for the SmartScreen and Gatekeeper prompts. Then try it:

```
eyewall --demo         # replay the bundled recording of Hurricane Erin (2025)
eyewall                # live data
```

## With Python 3.12 or newer

```
pipx install eyewall         # or: uv tool install eyewall, or: pip install eyewall
```

(Once the project is published to PyPI; until then, `pipx install git+https://github.com/WPTK/eyewall`.)

## Checking an installation

`eyewall --selftest` replays an hour of the bundled storm through every parser and draws one map frame. It prints
`selftest ok` and exits 0, or names the failure and exits 1.

## Settings

The first save from the settings screen (`S`, then `Ctrl+S`) creates `config.toml` in the per-user config directory
(`%APPDATA%\eyewall` on Windows, `~/.config/eyewall` on Linux, `~/Library/Application Support/eyewall` on macOS).
`--config PATH` reads another file; `--no-config` ignores the file for one run.
