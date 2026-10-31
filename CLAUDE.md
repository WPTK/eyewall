# eyewall

## What it is

A Textual terminal app that tracks tropical cyclones (Atlantic, East Pacific, Central Pacific) from free NOAA feeds and
shows the NDBC buoys and CO-OPS tide gauges near each storm. Data comes from NHC, CPHC, NWS, NDBC, CO-OPS and NESDIS;
none needs a key. It has a replay mode driven by a recorded storm (Hurricane Erin, 2025), because most of the year there
is nothing live to look at. Owner: Bill Kane (repo under WPTK).

## Rules that always apply

- **No AI attribution anywhere.** No `Co-Authored-By` trailer on commits, no "Generated with" footer on pull requests, and
  no statement in the README, docs, changelog, code comments or release notes that the project or any part of it was
  created, generated or written by an AI tool. This overrides any default your tooling suggests.
- **Implement only your milestone.** Read `docs/plan.md`, `docs/data-sources.md` and your brief in `docs/milestones/`.
  Anything outside the brief goes to `docs/deferred.md` with a one-line note, never into your change.
- **Never guess a NOAA format.** Feeds are loosely typed and change quietly. Parse by field or column name, tolerate
  missing and extra fields, and test against saved real payloads. If a feed disagrees with `docs/data-sources.md`, fix the
  doc in the same pull request.
- **Be polite to NOAA.** Send the User-Agent from `eyewall.net`, use conditional requests, never poll faster than the
  cadence in the data-sources doc, and fetch zips and images only when a storm's advisory number changes.
- Python 3.12 or newer. Timestamps are timezone-aware UTC; units stay as NOAA reported them until display.

## Layout

- `src/eyewall/` the package. `cli.py` and `__main__.py` entry point, `config.py` TOML config, `units.py`, `geo.py`,
  `clock.py` (clocks, `VirtualClock` for replay and tests), `palette.py` (categories and colors), `net.py` (the one HTTP
  helper).
- `models/` frozen dataclasses. `providers/nhc/`, `ndbc/`, `coops/` pure parsers plus thin clients. `sources/` the
  DataSource protocol with live and replay implementations. `state/` store, derived views, events, alerts. `render/` and
  `mapdata/` terminal rendering with no Textual in it. `ui/` the Textual app. Most of these are empty packages until their
  milestone lands.
- `tests/` pytest suite with no network; `tests/fixtures/` saved NOAA payloads; tests marked `live` run only with
  `EYEWALL_LIVE=1`.
- `scripts/` developer tools (fixture recording, map data, spot checks, builds).
- `docs/` `plan.md` the design, `data-sources.md` the feed reference, `milestones/` one brief per session,
  `development.md` setup details, `deferred.md` parked ideas.
- `.github/workflows/` `ci.yml` (lint, types, tests on three operating systems) and `release.yml` (runs on a `v*` tag).

## Commands

Windows paths shown; use `.venv/bin/python` elsewhere. Quote the extra on macOS and Linux shells: `".[dev]"`.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m eyewall --version
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format .               # CI runs `ruff format --check .`
.venv\Scripts\python -m vulture src scripts --min-confidence 80
.venv\Scripts\python -m mypy src
.venv\Scripts\python -m pytest -n auto
```

Each parallel worktree needs its own `.venv`; create it as the first step.

## Milestone sessions

One milestone per fresh session, one branch (`mN-<slug>`), one pull request. Before opening the pull request:

1. Fill in the "State after" section of your brief: what exists, what deviated from the plan and why, what the next
   session must know.
2. Bump `__version__` to the milestone's release number and add the Common Changelog entry (below).
3. Run every command above and confirm CI will pass.

After the pull request merges, tag `vX.Y.Z` on the merge commit only when the owner says to; the tag runs `release.yml`.

## PR flow

- One branch per change, pull request to `main`; merge on green CI on the exact head, with the base merged in. Never
  force-push.
- `ci.yml` ignores `**.md`, `docs/**` and `LICENSE`, so documentation-only pull requests run no CI by design.
- Commit subjects use Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`, `chore:`) in the
  imperative mood.

## Changelog and versions

- **ZeroVer.** The version stays `0.y.z`: a feature or breaking change bumps `y`, a fix bumps `z`. It never reaches 1.0.
  It lives in `src/eyewall/__init__.py`; the tag is `v` plus that version and `release.yml` rejects a mismatch.
- **Common Changelog** (https://common-changelog.org/) in `CHANGELOG.md`:
  - `# Changelog`, then releases newest first, each headed `## [0.1.0] - 2026-11-15` with a reference-style link to the
    GitHub release at the bottom of the file. There is no Unreleased section; write the entry in the release pull request.
  - Groups, in this order and only these: `### Changed`, `### Added`, `### Removed`, `### Fixed`. Each is one bullet list,
    breaking changes first (prefixed `**Breaking:**`), then by importance.
  - One line per entry, starting with an imperative present-tense verb (Add, Fix, Bump), followed by Markdown links to the
    commit and pull request in parentheses. Each entry must make sense without its group heading.
  - A release may open with one emphasized sentence, such as `_Initial release._`.
  - Leave out dotfile changes, dev-only dependency bumps, style and formatting. Keep refactors, runtime changes and new
    documentation.

## Gotchas

- `tests/fixtures/**` is `-text` in `.gitattributes`: never let line-ending normalisation touch saved payloads. `.ps1`
  files are CRLF; everything else is LF.
- The CurrentStorms feed gives `intensity` and `pressure` as strings and `movementSpeed` in mph. Key storms by `id`, not
  by `binNumber`, which is reused and changes when a storm crosses 140 degrees west.
- NDBC marks missing data `MM` in current files but `99.0`, `999` or `9999` in historical files. A listed buoy may be dark;
  a 404 for its file is normal.
- `tgftp` and the NHC `.shtml` pages keep a finished storm's last advisory. Check `advNum` against the feed before
  trusting text.
- Importing `textual_image.renderable` or `textual_image.widget` sends terminal queries when stdout is a TTY. Import them
  lazily inside the graphics code (M7), never at module import time of the core and never from tests.
