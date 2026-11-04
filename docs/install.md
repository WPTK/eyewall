# Install

eyewall needs a terminal. A modern one (Windows Terminal, iTerm2, GNOME Terminal, kitty) draws the map best. eyewall
reads free NOAA feeds and needs no account or key. It is not an official warning source. For decisions that matter, use
the National Hurricane Center and your local National Weather Service office.

## A standalone binary

Download the file for your platform from the [releases page](https://github.com/WPTK/eyewall/releases) and run it. You
do not need Python.

| Platform | File |
| --- | --- |
| Windows, x86_64 | `eyewall-windows-x86_64.exe` |
| Linux, x86_64 | `eyewall-linux-x86_64.tar.gz` |
| Linux, arm64 | `eyewall-linux-arm64.tar.gz` |
| macOS, Apple silicon | `eyewall-macos-arm64.tar.gz` |
| macOS, Intel | `eyewall-macos-x86_64.tar.gz` |

Check the download against `SHA256SUMS` from the same release. On Linux and macOS, unpack the archive. It holds one
executable file, `eyewall`, with the executable bit set, so you do not need `chmod`.

```
# Linux (x86_64 shown)
mkdir eyewall-bin && tar -C eyewall-bin -xzf eyewall-linux-x86_64.tar.gz && ./eyewall-bin/eyewall --demo

# macOS (Apple silicon shown); the second line clears the quarantine flag
mkdir eyewall-bin && tar -C eyewall-bin -xzf eyewall-macos-arm64.tar.gz
xattr -d com.apple.quarantine eyewall-bin/eyewall
./eyewall-bin/eyewall --demo
```

```
# Windows (PowerShell)
.\eyewall-windows-x86_64.exe --demo
```

The binaries are not signed. On Windows, SmartScreen may warn on first run. Choose "More info", then "Run anyway". On
macOS, the `xattr` command above clears the "unidentified developer" block.

## With Python 3.12 or newer

You need `git`. Any one of these commands installs the default branch and puts `eyewall` on your path:

```
uv tool install git+https://github.com/WPTK/eyewall
pipx install git+https://github.com/WPTK/eyewall
python -m pip install git+https://github.com/WPTK/eyewall
```

To work on eyewall from a clone, follow `docs/development.md`.

## Supported systems

- Windows 11 is the supported Windows. CI and the binary build run on GitHub's `windows-latest` (Windows Server), which
  stands in for the console but is not a Windows 11 test. Older Windows is not supported.
- The Linux binaries are built on Debian 11 (glibc 2.31) and work on any glibc 2.31 or newer distribution, such as
  Debian 11 and Ubuntu 20.04 and later. Alpine and other musl systems are not supported: the binary does not start
  there.
- The macOS Apple silicon binary needs macOS 14 or later, and the Intel binary needs macOS 15 or later. The
  pinned `pyproj` wheels that the binaries bundle set those floors. The Python routes above work on older versions.

## Check an installation

`eyewall --selftest` replays an hour of the bundled storm through every parser and draws one map frame. It prints
`selftest ok` and exits 0, or names the failure and exits 1.

## Settings

eyewall runs without a config file. The first save from the settings screen (`S`, then `Ctrl+S`) creates `config.toml`
in your user config directory:

- Windows: `%LOCALAPPDATA%\eyewall\config.toml`
- Linux: `~/.config/eyewall/config.toml`
- macOS: `~/Library/Application Support/eyewall/config.toml`

`--config PATH` reads another file, and `--no-config` ignores the file for one run. `docs/configuration.md` lists every
key.
