# Development

## Setup

Python 3.12 or newer. From a fresh clone:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

On macOS and Linux use `.venv/bin/python` and quote the extra, `".[dev]"`. The editable install means code changes take
effect without reinstalling; `__version__` is read from `src/eyewall/__init__.py` when the package is installed, so
reinstall after bumping it if you want `pip` metadata to agree.

Each git worktree needs its own `.venv`; create it before anything else.

## Checks

CI runs these on Windows, Linux and macOS with Python 3.12 and 3.13 (3.14 on Linux is informational). Run them locally
before every pull request:

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .      # drop --check to rewrite files
.venv\Scripts\python -m vulture src scripts --min-confidence 80
.venv\Scripts\python -m mypy src
.venv\Scripts\python -m pytest -n auto
.venv\Scripts\python -m eyewall --version
```

Ruff uses a 120 column limit. Mypy requires annotations on every function in `src/`. Vulture only reports unused code it
is nearly certain about, so a report means a real leftover.

## Tests

- The suite never touches the network. Parsers are tested against saved real payloads in `tests/fixtures/`, recorded with
  the scripts in `scripts/`. Add a fixture for every odd case you handle (a missing field, a fill value, a dark station).
- A test that runs past 120 seconds (300 for UAT) is stopped by `pytest-timeout`. Windows has no `SIGALRM`, so the
  plugin uses its thread method there: it prints every thread's stack and ends the whole pytest process, which fails the
  run but reports no summary. On Linux and macOS, `--timeout-method=signal` fails only the one test. A test process
  whose memory passes 2 GB is killed with exit status 70 and no summary (a watcher thread in `tests/conftest.py`;
  `resource.setrlimit` does not exist on Windows). The full suite peaks under 700 MB and its slowest test takes about 11 s. `EYEWALL_TEST_RSS_MB=0` turns the memory
  watch off and `--timeout=0` the time limit.
- HTTP is mocked with `respx`. Time comes from `eyewall.clock.VirtualClock`, never from `sleep`.
- Tests marked `live` call the real NOAA services and run only with `EYEWALL_LIVE=1`:

  ```powershell
  $env:EYEWALL_LIVE = "1"; .venv\Scripts\python -m pytest -m live
  ```

- Interface tests use Textual's `App.run_test()` and its `Pilot`. `tests/test_textual_api.py` shows the pattern, including
  a widget that paints its own lines the way the map will. Snapshot tests use `pytest-textual-snapshot`; update them only
  after an intentional visual change.
- The UAT suite in `tests/uat` drives the whole app over the bundled Erin recording, with no network. It runs at the
  sizes the main screen is built around: 80x24 (the floor), 100x40, 100x50, 120x30, 200x50 and 280x70, plus the
  too-small case (below 60x16, where the app shows the size it needs), live resizes between them, and the
  command-line paths. Navigation is checked with real mouse clicks (a storm or a buoy on the map, a card's `open >`
  link, a list row, the breadcrumb, a footer key, the feed-health slot) as well as keys, and every screen is visited at
  every size. Every step is checked (no error toast or logged error, nothing clipped, a one-row footer ending in
  `? help`) and saved as an SVG screenshot. Run it with `python -m pytest tests/uat -m uat`, or with
  `python scripts/uat.py [OUT_DIR]`, which also renders each screenshot to PNG through Edge (default directory: a new
  temporary one, never the repository). Set `EYEWALL_UAT_OUT` to choose where `pytest` writes the SVG files.
- `eyewall --demo --summary` and `eyewall --demo --summary --until +20h` print the plain-sentence summary of the
  recording at two moments; `tests/test_words_*.py` pin the wording. Run the app once with `NO_COLOR=1` and read each
  screen: every cue must still have a word, glyph or pattern.
- `python scripts/screenshots.py` rewrites the README pictures in `docs/images`. It clears `NO_COLOR` (set in some shells and
  agent sessions, it turns Textual monochrome) and fails if a picture has no chromatic colour.
- `textual_image.renderable` and `textual_image.widget` send terminal queries when imported with stdout on a TTY. Import
  them lazily, only where images are drawn.

## Real-input run on the built exe

`tests/realinput` runs the built artifact, not the source, and drives it the way a terminal does. It starts the Windows
exe from an empty directory with no repo, no venv and no config (`HOME`, `USERPROFILE`, `APPDATA` and the `XDG_*`
variables point at empty temp directories) on a ConPTY pseudo-console (pywinpty), writes the bytes a terminal sends
(key sequences, SGR mouse move, press and release, wheel) and reads the screen back through pyte, so Textual's real input
parser runs. The driver is the vendored `tests/uat_kit/` (from wxbrief, commit noted in each file); `tests/realinput/app.py`
is the eyewall adapter that knows where the crumb, footer and marks are.

```powershell
$env:EYEWALL_EXE = "dist\eyewall.exe"     # a build from scriptsuild_exe.ps1, or any exe
.venv\Scripts\python -m pytest tests/realinput -m realinput
.venv\Scripts\python scripts/realinput.py --exe dist\eyewall.exe    # same, plus one results table (also saved as JSON)
```

Without `EYEWALL_EXE` the suite downloads the release asset `eyewall-windows-x86_64.exe` of `EYEWALL_RELEASE` (default
`v0.9.0`) into an empty temp directory. The tests are marked `realinput` and do not run in the default suite or in CI;
`tests/realinput/test_helpers.py` (the harness's own tests, no exe needed) does. The run takes about 20 minutes. Results
go to `EYEWALL_REAL_RESULTS` (default: the temp directory). Every walkthrough item prints PASS, FAIL, XFAIL or SKIP with the
assertion that decided it. A defect found by the run is filed as an issue and listed in `tests/realinput/known.py`; its
item is then expected to fail and the run fails when it starts passing, so the entry has to be deleted with the fix.

## Configuration while developing

The config file lives in the platform config directory (on Windows, `%LOCALAPPDATA%\eyewall\config.toml`). Pass
`--config PATH` to use another file or `--no-config` to ignore it. Command-line flags always win and are never saved.

## Terminals

Windows Terminal, iTerm2, Kitty and most modern terminals render the braille map and Unicode symbols. The legacy Windows
console (conhost) does not, so use `--glyphs ascii` there. Inline images need a terminal that supports Sixel or the Kitty
graphics protocol; everywhere else eyewall falls back to a drawn approximation.

## Working on NOAA data

- Never guess a feed format. NOAA feeds are loosely typed and change without notice. Parse by field or column name,
  tolerate missing and extra fields, and test against saved real payloads. If a feed disagrees with `data-sources.md`,
  fix that file in the same pull request.
- Be polite to NOAA. Requests go through `eyewall/net.py`, which sends the User-Agent from `eyewall.net` and uses
  conditional requests. Never poll faster than the cadence in `data-sources.md`, and fetch zips and images only when a
  storm's advisory number changes.
- Timestamps are timezone-aware UTC. Units stay as NOAA reported them until display.
- Fixtures: `tests/fixtures/**` is marked `-text` in `.gitattributes`, so line-ending normalisation must never touch a
  saved payload. `.ps1` files are CRLF; everything else is LF.
- Things that have bitten before:
  - The CurrentStorms feed gives `intensity` and `pressure` as strings and `movementSpeed` in mph. Key storms by `id`,
    not by `binNumber`, which is reused and changes when a storm crosses 140 degrees west.
  - NDBC marks missing data `MM` in current files but `99.0`, `999` or `9999` in historical files. A listed buoy may be
    dark; a 404 for its file is normal.
  - `tgftp` and the NHC `.shtml` pages keep a finished storm's last advisory. Check `advNum` against the feed before
    trusting text.

## Pull requests

One branch per change and a pull request to `main`; merge when CI is green on the exact head, with `main` merged in.
Do not force-push. Commit subjects use Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`,
`chore:`) in the imperative mood. `ci.yml` ignores `**.md`, `docs/**` and `LICENSE`, so documentation-only pull
requests run no CI.

## Versions and the changelog

The version is ZeroVer, `0.y.z`: a feature or breaking change bumps `y`, a fix bumps `z`, and it never reaches 1.0. It
lives in `src/eyewall/__init__.py`. The tag is `v` plus that version, and `release.yml` rejects a mismatch.

`CHANGELOG.md` follows [Common Changelog](https://common-changelog.org/):

- `# Changelog`, then releases newest first, each headed `## [0.1.0] - 2026-11-15` with a reference-style link to the
  GitHub release at the bottom of the file. There is no Unreleased section; the entry is written in the release pull
  request.
- Groups, in this order and only these: `### Changed`, `### Added`, `### Removed`, `### Fixed`. Each is one bullet list,
  breaking changes first (prefixed `**Breaking:**`), then by importance.
- One line per entry, starting with an imperative present-tense verb (Add, Fix, Bump), followed by links to the commit
  and pull request in parentheses. Each entry must make sense without its group heading.
- Leave out dotfile changes, dev-only dependency bumps, style and formatting. Keep refactors, runtime changes and new
  documentation.

## Releases

A release pull request bumps the version and adds the changelog entry. After it merges, the maintainer tags the merge
commit:

```bash
git tag v0.1.0
git push origin v0.1.0
```

`release.yml` then checks that the tag, `__version__` and the changelog heading agree, builds the wheel and source
distribution and the five standalone binaries (`binaries.yml`, which also runs on pull requests that touch the build and
can be started by hand as a dry run), hashes them into `SHA256SUMS`, and creates the GitHub release using that changelog
section as its notes. The Linux and macOS binaries are built to ship as `.tar.gz` archives so they keep the executable
bit. The binaries are built with the pins in `scripts/binary-constraints.txt`; refresh them with
`python scripts/update_constraints.py` (`--check` shows drift; Dependabot does not touch that file) before a release. The Linux x86_64 binary is built inside
`python:3.12-bullseye` so it runs on glibc 2.31 or newer. `canary.yml` is a scheduled workflow, which GitHub disables
after 60 days without repository activity; run it by hand to re-enable it. It runs daily and never on pull
requests: a format failure opens or comments on a `feed-drift` issue at once, while a feed that is only down or empty
(spot check exit status 2) raises a `feed-down` issue after three failed runs in a row. `scripts/build_exe.ps1` builds the Windows
binary locally.

Before announcing a release, run the binary for each platform on a machine with no Python and check:

1. `eyewall --version` prints the release number and `eyewall --selftest` prints `selftest ok`.
2. `eyewall --demo --headless --until +1h` prints three events and `3 event(s)`.
3. `eyewall --demo` opens at 80x24 and at 120x30: the map draws, Space pauses, `Enter` opens the Storm screen, `t`, `b`
   and `g` open the NHC text, Buoys and gauges and Pictures screens, a click on a buoy opens its Station screen, `?`
   shows help, `Esc` goes back and `q` restores the terminal. `eyewall --demo --summary` prints sentences and exits 0.
4. Live, `eyewall` starts and either lists the active storms or says `No tropical cyclones`; out of season that is
   correct. Offline it still opens and marks the feeds as waiting.
5. The binaries are not signed, so expect the SmartScreen and Gatekeeper prompts described in `install.md`.