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

**What exists.**

- `sources/protocol.py` (`DataSource`, the feed names), `sources/cache.py` (a caching `httpx` transport: ETag and
  Last-Modified validators, a 304 answered with the cached body, a stale copy served when the network fails or the
  server answers 429 or 5xx), `sources/live.py` (`LiveSource`, which marks a feed stale when any of its requests came
  from the cache), `sources/replay.py` and `sources/bundle.py` (the bundle format and its loader).
- `poll.py` (`Poller`): six feeds on the `[poll]` intervals, a freshness model (loading, fresh, stale, error; stale
  after 2.5 intervals or when the source answered from its cache), exponential backoff, away mode (intervals times 3),
  `refresh()`, injectable clock and sleep. The storm products are fetched only when a storm's newest advisory number or
  `lastUpdate` changes; alerts are polled only while a storm is a US threat; buoy series and tide gauges run at most
  four at a time, staggered.
- `state/store.py`, `state/events.py`, `state/alerts.py`: the store with nearby buoys and gauges, the pure event diffs,
  the `[alerts]` rules and the seen set (`seen_events.json` under `user_data_dir("eyewall")`, keys pruned after 30 days).
- `eyewall --replay BUNDLE|demo`, `--demo`, `--headless`, `--until +12h|ISO`, `--state-dir`. Headless replay polls on the
  virtual clock and prints one line per event; without `--replay` it polls the live services once (or for `--until +30m`).
- `scripts/record_storm.py` and the trimmed Erin bundle at `tests/fixtures/replay/erin2025/` (4.6 MB, 19 August 03Z to
  21 August 12Z, eight buoys, three tide gauges, two cone graphics). The wheel ships it as `eyewall/demo/erin2025`
  (hatch `force-include`); a source checkout reads it from the fixtures. `scripts/spot_check_live.py` runs the live
  source, cuts the network and checks that feeds go stale.

**Result.** `eyewall --replay demo --headless --until +12h` logs 13 events: advisories 31, 31A, 32, 32A and 33; the
buoy 41047 crossing 34 kt at 03:10Z; at advisory 33 the Storm Surge Warning issued, the tropical storm watch and warning
changes and the Storm Surge Watch discontinued; and discussions 32 and 33. A second run on the same state directory logs
none.

**Deviations from the brief and from the plan.**

- The bundle window is 19 to 21 August (the brief said about three days around the crossings), chosen so that `+12h`
  covers four advisories, the first 34 kt buoy crossing and the surge warning. The bundle also holds the intermediate
  advisories (`public_a/b/c`), which the brief's layout did not list.
- Event rules: watches and warnings, classification changes and discussions are compared with the previous state, so what
  was already in effect at the first load is not news; storms, advisories and outlooks are keyed by identity and
  de-duplicated by the seen set. Buoy crossings count when they happened within three hours of the poll, silence when the
  buoy stopped within the last day. Keys are (storm id, advisory number, kind) plus a subject (the watch label, the
  station and threshold), because one advisory can carry several of the same kind.
- A storm's advisory number for change detection is the newest across its products (`state.events.current_adv`), not
  `Storm.adv_num`, which prefers the forecast advisory and so misses intermediate advisories (31A has only a public
  advisory).
- M1 fixes: the four text heading patterns tolerate NHC's `...RESENT` suffix (the archive has advisories 22 and 35 of Erin
  that way; the recorder found it); `ids.ARCHIVE_KINDS` gained `public_a/b/c`; `NhcClient` gained `radii_gis()` and the
  `fallback` switch on `advisory()`, `outlook_text()` and the API text fetch, which also takes the list's validators.
- The replay serves no outlook, invests, alerts or satellite (empty values); the bundle format has no place for them yet.
- The Erin b-deck starts at 06Z on 19 August, so the replay has no past track for its first three hours.

**What the next session must know.**

- The UI (M5) reads `Store` and `Poller`; build `Poller(source, store, AlertEngine(config.alerts, state_dir), config.poll,
  clock=..., on_events=..., idle_for=...)`, call `run()` in a worker and `observe_presence()` once a second. For a replay,
  pass the `ReplaySource.clock` (a `VirtualClock`) as the poller's clock and advance it; `step_advisory(+1|-1)` jumps the
  clock to the next or previous advisory.
- `Poller.on_result` reports every feed attempt with its `Freshness` for the status bar; `Freshness.from_cache` is the
  offline marker.
- `Store.tendency(station, now)` is the only place a pressure tendency should come from (it refuses a quiet station);
  `state.store.track_fixes(state)` gives the nearby-station inputs with hours counted from the center.
- Tide gauges use MLLW, or IGLD for `great_lakes` gauges; a gauge that errors is in `Store.tide_errors`, not an exception.
- Poll granularity in a replay is the storms interval (300 s), so an event is stamped up to five minutes after the
  advisory's issue time.
