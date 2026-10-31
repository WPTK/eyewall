# M4 Core

## Goal

The data source abstraction with a live and a replay implementation, the store and event logic, the multi-feed poller, and
a recorded Hurricane Erin bundle, all runnable without a UI. Release 0.4.0.

## Depends on

M1 and M2 merged. M3 is not needed.

## Scope

- `sources/protocol.py`: the async `DataSource` protocol (storms, advisory products, forecast and best-track GIS, outlook,
  alerts, graphics, NDBC stations, latest observations and series, CO-OPS stations and series, `now()`).
- `sources/cache.py`: raw-payload disk cache under `platformdirs.user_cache_dir("eyewall")` with ETag and Last-Modified
  validators, so a launch paints instantly and an offline launch shows the last data marked stale.
- `sources/live.py`: composes the M1 and M2 clients with the cache.
- `sources/replay.py` and the bundle format: a directory with `manifest.toml`, `atcf/b*.dat`,
  `nhc/<storm>/<advNum>.{tcm,tcp,tcd}.txt`, `gis/<storm>/<advNum>_5day.zip` and `_fcst.zip`, `ndbc/activestations.xml`,
  `ndbc/<station>.stdmet.txt`, `coops/<station>.*.json` and `graphics/`. A `VirtualClock` drives it: at time T it builds
  CurrentStorms from the b-deck and the latest advisory at or before T, and latest observations from each series' rows at or
  before T. Stepping to a previous advisory moves the clock backwards. `--replay BUNDLE` and `--demo` select it.
- `scripts/record_storm.py AL052025 --from 2025-08-15 --to 2025-08-23 --stations auto` builds a bundle from the NHC archive
  pages, the GIS archive zips, `atcf/archive/2025/bal052025.dat.gz`, the NDBC monthly and yearly historical files and CO-OPS
  date ranges (auto picks stations within 300 nm of the best track). Commit a trimmed bundle (about three days, eight
  stations, two graphics) at `tests/fixtures/replay/erin2025/` and make it what `--demo` loads (ship it inside the package
  if needed).
- `poll.py`: adapt cfbtui's `PollScheduler` (fetch it with `gh api -H "Accept: application/vnd.github.raw+json"
  repos/WPTK/cfbtui/contents/cfbtui/poll.py`): freshness model, injectable clock, exponential backoff, `refresh()` wake,
  away mode that triples intervals. Feeds and defaults: storms 300 s, outlook 1800 s, alerts 300 s while a US threat exists,
  buoys 600 s (the latest-obs file, then the nearby stations' 5-day files, staggered, at most four in flight), tides 360 s,
  satellite 600 s. Text, GIS zips and b-decks refetch only when a storm's `advNum` or `lastUpdate` changes.
- `state/store.py`: storms with their advisory, forecast, GIS layers, best track, watches and warnings; outlook areas and
  invests; station catalogs; latest observations; watched series. Uses M2's `nearby` and `trends`.
- `state/events.py` and `state/alerts.py`: diff successive states into events (new storm, PTC or invest; new advisory
  including intermediates; classification change; watch or warning issued, changed or discontinued; new outlook;
  new discussion; a nearby buoy crossing 34, 50 or 64 kt; a buoy going silent) and apply the `[alerts]` rules. De-duplicate by
  (storm id, advNum, kind) and persist the seen set under `user_data_dir("eyewall")` so a restart does not re-fire.
- A headless mode for tests and demos: `eyewall --replay demo --headless --until +12h` runs the poller on the virtual clock
  and prints the events.

## Out of scope

Any Textual UI. Rendering. New parsers (fix bugs in M1 and M2 code if you find them, and note it).

## Done when

- The headless replay of the Erin bundle logs the expected advisory, watch and warning, and buoy events, and a second run
  against the same persisted state logs none of them again.
- The live source runs against the real services in a spot check and handles a dropped network by marking feeds stale.
- Poller tests use the virtual clock and cover backoff, away mode and the change-triggered refetch.
- All checks in `CLAUDE.md` pass; version is 0.4.0 with its changelog entry; State after is filled in and the status in
  `docs/milestones/README.md` is updated.

## Verify

The commands in `CLAUDE.md`, plus `python -m eyewall --replay demo --headless --until +12h`.

## State after

(to be filled in by the session)
