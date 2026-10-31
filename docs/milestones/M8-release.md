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

(to be filled in by the session)
