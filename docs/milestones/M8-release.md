# M8 Polish and release

## Goal

A first release people can install and trust: documentation, screenshots, a weekly check for feed drift, and standalone
binaries. Release 0.8.0.

## Depends on

M7 merged.

## Scope

- README with a current description, screenshots from the replay (`scripts/screenshot_terminal.ps1`), install instructions
  (pip, pipx, uv, or a release binary) and an honest note that this is not an official warning source.
- `docs/replay.md`: how replay works, how to record another storm with `scripts/record_storm.py`.
- `.github/workflows/canary.yml`: weekly, fetch each live endpoint once with `spot_check_nhc.py` and `spot_check_obs.py` and
  open or update an issue when a parser fails (adapt cfbtui's `espn-canary.yml`).
- PyInstaller one-file builds: `eyewall.spec`, `scripts/build_exe.ps1`, and release jobs for Windows x86_64, Linux x86_64 and
  arm64 (built in a Debian 11 container for older glibc), and macOS arm64 and x86_64, with a `SHA256SUMS` file attached to the
  release. Model them on cfbtui's `release.yml` and `cfbtui.spec`. Include map data, the demo bundle and Textual's data
  files. Add a `--selftest` flag that exercises the parsers and renders one frame headlessly, and run it in CI against the
  built binary.
- First-run and offline polish: a friendly state when there is no network and no cache, a first-run hint about the config
  file, and a `docs/smoke-test.md` checklist for a manual pass on a machine without Python.
- Review `docs/deferred.md` and move anything that bites into this milestone or leave it parked.

## Out of scope

Self-updating binaries, new features.

## Done when

- `dist\eyewall.exe --replay demo` runs on a Windows machine without Python, and `dist\eyewall.exe --selftest` passes.
- The release contains the wheel, the source distribution, five binaries and `SHA256SUMS`.
- The canary workflow runs green on demand.
- All checks in `CLAUDE.md` pass; version is 0.8.0 with its changelog entry; State after is filled in and the status in
  `docs/milestones/README.md` is updated.

## Verify

The commands in `CLAUDE.md`, a local binary build, and the smoke-test checklist.

## State after

**What exists.**

- `.github/workflows/canary.yml` (weekly, on demand): runs `spot_check_nhc.py` and `spot_check_obs.py`, opens or updates one
  `feed-drift` issue.
- `eyewall.spec`, `scripts/build_exe.ps1`, `scripts/pyinstaller-version.txt` (the one PyInstaller pin) and
  `.github/workflows/binaries.yml`, a reusable workflow that builds the five binaries (Linux in a digest-pinned
  `python:3.12-bullseye` container, glibc 2.31) and runs `--selftest` and a one hour demo replay on each. `release.yml`
  (tag only) builds the wheel and sdist, calls `binaries.yml`, writes `SHA256SUMS` (it must list exactly seven files) and
  publishes draft first, upload with `--clobber`, then undraft.
- `eyewall --selftest` (`cli._selftest`): the packaged stylesheet exists, an hour of the demo replays through the poller,
  one basemap frame draws.
- Docs: `docs/install.md`, `docs/replay.md`, `docs/smoke-test.md`; README rewritten with three screenshots in `docs/images/`
  written by `scripts/screenshots.py`.
- Interface polish, with no new features: the surge watch or warning listed once (warnings panel) and the freed rows given
  to the headline; one status bar indicator that names a source only when stale or failing; the storm list shows a basin
  only when it has storms or invests; theme scrollbars; a shorter help; `clock.format_when` for the Summary and buoy times;
  "no connection" on the storm list when nothing has ever answered; a toast naming the settings file on a first live run.

**Deviations.**

- The Ctrl+P clash with the command palette no longer exists: the palette is disabled (`ENABLE_COMMAND_PALETTE = False`),
  so the deferred note was removed.
- The scrollbar already appeared only where content overflows; only the colours changed.
- The Linux binaries stay on Debian 11 (past its LTS) on purpose, for the glibc 2.31 floor; the container image is pinned by
  digest and the pin moves deliberately.

**What the next session must know.**

- Nothing is tagged. To release: merge, then tag `v0.8.0` on the merge commit when the owner says so. The Linux, arm64 and
  macOS binaries and the release job have only run as dry runs of `binaries.yml`; the first real run of `release.yml` and the
  canary's issue step is the first tag and the first scheduled run. Run the canary once by hand after merging.
- Not verified in a real terminal: the Sixel and Kitty drawing (M7), the unsigned-binary prompts on Windows and macOS.
- Parked in `docs/deferred.md`: unpinned runtime dependencies in the CI builds, the executable bit lost through artifacts,
  the canary's traceback tail and the 60 day disable of scheduled workflows.
