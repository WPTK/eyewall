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

Each git worktree needs its own `.venv`. Create it before anything else when a milestone session starts in a new worktree.

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
- HTTP is mocked with `respx`. Time comes from `eyewall.clock.VirtualClock`, never from `sleep`.
- Tests marked `live` call the real NOAA services and run only with `EYEWALL_LIVE=1`:

  ```powershell
  $env:EYEWALL_LIVE = "1"; .venv\Scripts\python -m pytest -m live
  ```

- Interface tests use Textual's `App.run_test()` and its `Pilot`. `tests/test_textual_api.py` shows the pattern, including
  a widget that paints its own lines the way the map will. Snapshot tests use `pytest-textual-snapshot`; update them only
  after an intentional visual change.
- `textual_image.renderable` and `textual_image.widget` send terminal queries when imported with stdout on a TTY. Import
  them lazily, only where images are drawn.

## Configuration while developing

The config file lives in the platform config directory (on Windows, `%LOCALAPPDATA%\eyewall\config.toml`). Pass
`--config PATH` to use another file or `--no-config` to ignore it. Command-line flags always win and are never saved.

## Terminals

Windows Terminal, iTerm2, Kitty and most modern terminals render the braille map and Unicode symbols. The legacy Windows
console (conhost) does not, so use `--glyphs ascii` there. Inline images need a terminal that supports Sixel or the Kitty
graphics protocol; everywhere else eyewall falls back to a drawn approximation.

## Releases

Each milestone ends in a release. The pull request bumps the version and adds the changelog entry (see `CLAUDE.md`).
After it merges, the owner tags the merge commit:

```bash
git tag v0.1.0
git push origin v0.1.0
```

`release.yml` then checks that the tag, `__version__` and the changelog heading agree, builds the wheel and source
distribution and the five standalone binaries (`binaries.yml`, which also runs on pull requests that touch the build and can
be started by hand as a dry run), hashes them into `SHA256SUMS`, and creates the GitHub release using that changelog section
as its notes. `scripts/build_exe.ps1` builds the Windows binary locally; `docs/smoke-test.md` is the manual checklist.
