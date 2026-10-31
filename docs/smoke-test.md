# Smoke test

A manual pass on a machine that has no Python, run on each platform before a release is announced. Download the binary
for the platform and `SHA256SUMS` from the release page.

| Platform | File |
| --- | --- |
| Windows 10 or 11, x86_64 | `eyewall-windows-x86_64.exe` |
| Linux x86_64 (glibc 2.31 or newer) | `eyewall-linux-x86_64.tar.gz` |
| Linux arm64 (Raspberry Pi OS 64-bit) | `eyewall-linux-arm64.tar.gz` |
| macOS, Apple silicon | `eyewall-macos-arm64.tar.gz` |
| macOS, Intel | `eyewall-macos-x86_64.tar.gz` |

The binaries are not signed. Windows SmartScreen may warn on first run ("More info", then "Run anyway"); on macOS clear
the quarantine flag with `xattr -d com.apple.quarantine eyewall`.

## Checklist

1. Verify the download: `sha256sum -c --ignore-missing SHA256SUMS` (Linux, macOS) or
   `Get-FileHash eyewall-windows-x86_64.exe` and compare with the line in `SHA256SUMS` (Windows).
2. On Linux and macOS, unpack the archive (`tar -xzf`); the `eyewall` inside is already executable.
3. `eyewall --version` prints the release number.
4. `eyewall --selftest` prints `selftest ok` and exits 0.
5. `eyewall --demo --headless --until +1h` prints three events and `3 event(s)`.
6. `eyewall --demo` opens the interface in a terminal at least 100 columns wide:
   - The map shows the coastline, land, borders and Hurricane Erin with its cone and track.
   - Space pauses and resumes, `>` speeds the replay up, `]` jumps to the next advisory.
   - `Enter` opens the storm detail; on its Buoys tab `Enter` opens a buoy's charts and they draw; `Esc` goes back.
   - `?` shows help, `S` the settings, `A` the alert log, `q` quits and restores the terminal.
7. Live, with a network: `eyewall` starts, shows the status bar feeds turning fresh, and either lists the active
   storms or says `No tropical cyclones` per basin. Out of season that quiet state is correct.
8. Offline: disconnect the network and start `eyewall`. The interface still opens; the status bar marks the feeds as
   waiting, and `OFFLINE: cached data` appears once a cache exists.
9. First run: with no config file the app starts on defaults. After changing a setting and saving (`Ctrl+S` in the
   settings), the file appears in the per-user config directory (`%APPDATA%\eyewall\config.toml` on Windows,
   `~/.config/eyewall/config.toml` on Linux, `~/Library/Application Support/eyewall/config.toml` on macOS).
10. The graphics tab (after M7) opens and draws the cone still in a terminal that supports images, and degrades to text
    in one that does not.

Record the platform, the terminal and the version in the release pull request.
