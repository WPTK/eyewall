# M0 Scaffold and handoff

## Goal

A repository that installs, lints, type-checks and tests cleanly on three operating systems, carries the working rules, and
gives every later session what it needs to start without any conversation history.

## Depends on

Nothing.

## Scope

- Packaging (`pyproject.toml`, hatchling, `src/` layout), `LICENSE`, `.gitignore`, `.gitattributes`.
- `ci.yml` (ruff, format check, vulture, mypy, pytest on Windows, Linux and macOS) and `release.yml` (tag, version and
  changelog must agree; builds and publishes the wheel and source distribution).
- Shared modules every milestone imports: `config.py` (tolerant TOML loader), `units.py`, `geo.py`, `clock.py`
  (`VirtualClock`), `palette.py` (Saffir-Simpson categories and colors), `net.py` (User-Agent, conditional GET, retries),
  and a `cli.py` stub with the flags later milestones use.
- Empty subpackages for every directory in the layout, so parallel milestones never both create the same `__init__.py`.
- `CLAUDE.md`, `README.md`, `CHANGELOG.md` (heading only), `docs/`, and these briefs.
- A Textual smoke test that proves the line-rendering API the map depends on works in the installed Textual.

## Out of scope

Any parser, any UI, any network feed.

## Done when

CI is green on all three operating systems, `python -m eyewall --version` prints `0.0.1`, and a fresh session can start M1,
M2 or M3 from the repository alone.

## Verify

The commands in `CLAUDE.md`.

## State after

- Delivered as planned, with these additions: `net.py` (shared fetch helper) and `palette.py` were added to M0 so that M1
  and M2, which run in parallel, do not each write their own; `scripts/spot_check.py` was split into
  `spot_check_nhc.py` (M1) and `spot_check_obs.py` (M2) for the same reason.
- 91 tests pass locally on Windows with Python 3.12.
- No release tag: 0.0.1 is the scaffold, and 0.1.0 is the first release.
- Textual 8.2.8 is installed and `render_line` with `Strip` works in `run_test`. The snapshot plugin
  (`pytest-textual-snapshot` 1.1.0) installs and imports; its behaviour with Textual 8 is first exercised in M5.
- `textual_image.renderable` probes the terminal on import when stdout is a TTY, so it must be imported lazily (M7).
