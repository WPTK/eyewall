# M2 Observations data layer

## Goal

Parse NDBC and CO-OPS observations into dataclasses, and add the two pure pieces of logic that decide which stations
matter for a storm and what their readings are doing. Release 0.2.0.

## Depends on

M0. Runs at the same time as M1 and M3 in its own worktree. You own `src/eyewall/ndbc/`, `src/eyewall/coops/`,
`src/eyewall/models/obs.py`, `src/eyewall/state/nearby.py`, `src/eyewall/state/trends.py`, `tests/fixtures/ndbc/`,
`tests/fixtures/coops/`, `tests/test_ndbc_*.py`, `tests/test_coops_*.py`, `tests/test_nearby.py`, `tests/test_trends.py`,
`scripts/spot_check_obs.py` and `scripts/record_obs_fixtures.py`. Keep `state/__init__.py` and `models/__init__.py` as they
are. Do not depend on M1's models: define the small inputs you need in your own modules.

## Scope

Read `docs/data-sources.md` first; the NDBC and CO-OPS facts there decide most of the parsing rules.

- `ndbc/stations.py`: `activestations.xml` to `Station` (id, name, lat, lon, type, owner, program, and the
  reported-in-last-8-hours flags). Station ids can be seven characters; C-MAN ids are lowercase in the XML and uppercase in
  data file names, so normalise once.
- `ndbc/latest.py`: `latest_obs.txt`, parsed by header name. `MM` is missing. Waves are often missing in this file.
- `ndbc/stdmet.py`: one header-driven reader for `realtime2/{id}.txt`, `5day2/{id}_5day.txt` and the historical files
  (which use `99.0`, `999`, `9999` fills and have no PTDY column). Newest first in current files. Winds stay in m/s as
  reported; convert only for display.
- `ndbc/supl.py` and `ndbc/spec.py`: interval minimum pressure and peak wind with their times; the wave summary
  (compass text for swell and wind-wave direction).
- `ndbc/historical.py`: read the yearly `.txt.gz` and monthly `data/stdmet/{Mon}/` files for replay recording.
- `ndbc/client.py`: fetch the files above through `eyewall.net.fetch_bytes`. A 404 for a station file is normal (`allow_404`)
  and becomes "not reporting", not an error.
- `coops/stations.py`: the metadata API (`lng`, not `lon`). `coops/data.py`: `water_level`, `predictions` (hilo and
  interval), `air_pressure`, `wind`. Values are strings, missing is an empty string, quality flags are kept. One request per
  gauge; `datum` is required for water level. `coops/client.py` wraps the calls and sends `application=eyewall`.
- `models/obs.py`: `Station`, `Observation`, `ObservationSeries`, the supplemental and wave records, `TideStation`,
  `WaterLevelReading`, `Prediction`. Every measurement is optional.
- `state/nearby.py`: define `TrackFix(hours, lat, lon)` and a function that picks stations near a storm. A station counts
  when its distance to the current center is within `radius_now_nm`, or its distance to the forecast track (interpolated
  hourly out to `track_hours` with `eyewall.geo.interpolate`) is within `radius_track_nm`; watchlist stations are always in;
  rank by current distance and cap at `max_stations`. Report distance, bearing, closest approach and the time to it.
- `state/trends.py`: three-hour pressure tendency (use PTDY when present, otherwise compute from the series), wind and gust
  trend, observation age, a "silent" flag for a station that was reporting and stopped, and the interval minimum pressure and
  peak gust.
- `scripts/record_obs_fixtures.py` saves the payloads below; `scripts/spot_check_obs.py` fetches each feed once, parses it
  and prints a summary, including one dark buoy shown as "not reporting".

Fixtures: a trimmed `latest_obs.txt` with several `MM` rows; `41010` 5day, `.supl` and `.spec` files; a 2025 historical
sample for one Atlantic buoy; a trimmed `activestations.xml`; CO-OPS `water_level` (latest and a recent window with
empty-string gaps), `predictions` (hilo), `wind`, `air_pressure`, and a trimmed `stations.json`; and a 404 case (42040 or
41001 are dark as of 2026-10-31).

## Out of scope

Polling, caching, the store, any UI or rendering, anything about NHC storm feeds.

## Done when

- Parsers and the nearby and trends logic are covered by tests, including hand-computed distances for `nearby` and every
  fill-value convention.
- `python scripts/spot_check_obs.py` succeeds against the live services.
- All checks in `CLAUDE.md` pass; version is 0.2.0 with its changelog entry; State after is filled in and the status in
  `docs/milestones/README.md` is updated.

## Verify

The commands in `CLAUDE.md`, plus the spot check.

## State after

### What exists

- `models/obs.py`: frozen dataclasses with every measurement optional and the unit in the field name (`wind_speed_mps`,
  `pressure_hpa`, `level_ft`, `speed_kt`): `Station`, `Observation`, `LatestObservation`, `ObservationSeries` (newest
  first, empty means not reporting), `SupplementalReading`, `WaveSummary`, `TideStation`, `WaterLevelReading`,
  `Prediction`, `TideWind`, `TidePressure`, and `Parsed[T]`, the result of every list parser (`items`, `skipped`
  rows, and `message`, NOAA's own explanation when it had no data).
- `ndbc/`: `table.py` (the shared header-driven reader, per-column fill values, upper-casing of ids), `stations.py`,
  `latest.py`, `stdmet.py` (realtime2, 5day2 and historical files), `supl.py`, `spec.py`, `historical.py` (gunzip,
  `parse_historical`, `select_period`) and `client.py` (`NdbcClient`, URL builders, `Response[T]`).
- `coops/`: `stations.py` (listings plus `merge_tide_stations`), `data.py` (`datagetter_params` and one parser per
  product), `client.py` (`CoopsClient`: one request per call, `all_stations()` is two).
- `state/nearby.py`: `nearby_stations(center, track, stations, config=, watchlist=)` returns `NearbyStation` records
  (distance, bearing from the center, closest approach, hours to it, and why it is included). It works on anything with
  `id`, `lat` and `lon`, so NDBC stations and CO-OPS gauges share it. `TrackFix` and `hourly_track` are public.
- `state/trends.py`: `pressure_tendency`, `wind_trend`, `gust_trend`, `observation_age`, `is_silent`,
  `interval_extremes` and `station_trends`, which bundles them into one `StationTrends`.
- `scripts/record_obs_fixtures.py` (about 17 requests, one second apart) and `scripts/spot_check_obs.py` (about 14
  requests, 15 seconds, exit code 1 when a feed fails to fetch or parse). Fixtures and a `manifest.json` of where and
  when each was recorded are in `tests/fixtures/ndbc/` and `tests/fixtures/coops/`.

### Deviations from the brief

- **The historical sample is buoy 41025, not 41010.** 41010's 2025 yearly file stops on 31 July 2025 and has nothing
  from Hurricane Erin. The fixture is 41025's yearly file trimmed to 17 to 25 August 2025 (Erin passed with a lowest
  pressure of 996.9 hPa and a gust of 25.5 m/s), regzipped; the rows are untouched.
- **`docs/data-sources.md` was corrected** where the live services disagreed: the old `Aug/4101082025.txt.gz` example
  404s (monthly files exist only for the current year, the latest finished month is a plain `{id}.txt`, and the names
  for October to December are unknown), the historical `VIS` unit label, which stations are dark, the catalog flags,
  and the CO-OPS error behaviour, units and gaps. `monthly_url` refuses months 10 to 12 instead of guessing.
- **One generic `Parsed[T]` instead of a result class per parser, and a `Response[T]` wrapper in `ndbc/client.py`** so a
  304 (no value) and a 404 (an empty "not reporting" value) are explicit. CO-OPS methods return `Parsed[T]` directly.
- **CO-OPS series are newest first, like the NDBC ones**, although CO-OPS publishes them oldest first; predictions
  stay soonest first. Water level, wind and pressure are requested with `units=english` (feet, knots, millibars) and
  the field names say so.
- **Station ids are upper case everywhere** (`Station.id`, `LatestObservation.station_id`, `ObservationSeries`).
- Added beyond the brief, because the code needed them: `Parsed`, `merge_tide_stations`, `TideStation.products` (which
  listing a gauge came from, since only `type=met` says a gauge has wind and pressure) and `great_lakes`, and a DTD
  refusal in the catalog parser (the stdlib XML parser expands entities).

### What the next session must know

- **Forecast hours.** `TrackFix.hours` counts from the time of the storm's current center. The TCM counts forecast
  hours from the synoptic time 3 hours before the advisory (see `data-sources.md`), so M4 has to subtract that offset
  when it builds `TrackFix` values, or build them from valid times. The result of `nearby_stations` also carries
  `watchlisted`; pass `config.watchlist.ndbc` for buoys and `config.watchlist.coops` for gauges in separate calls.
- **Polling is M4's job.** The clients never sleep or limit concurrency. The plan's cadences (buoys 600 s, tides
  360 s, at most 4 station files in flight) must be enforced by the poller, which should also keep the `etag` and
  `last_modified` from each `Response` and pass them back.
- **Winds are not the same unit across feeds**: NDBC is m/s and CO-OPS is knots here; `units.convert` takes `mps` and
  `kt`. NDBC winds are 8-minute or 2-minute averages, not NHC's 1-minute kt.
- **Not reporting** is an empty `ObservationSeries` (`reporting` is False) and not `silent`; `silent` means the newest
  row is older than two hours. The catalog's `met` flag is False for buoys that have been dark for 8 hours, so a store
  can skip them before requesting a file; 42040, 41001 and 41002 were 404 on 2026-10-31.
- **Replay recording (M4)** should use `NdbcClient.historical_year` plus `select_period` for a past year; only the
  current year has monthly files. Check the buoy's coverage first: not every buoy has data for the storm dates.
- **The spot check is the format canary**: `scripts/spot_check_obs.py` is what `canary.yml` (M8) should run for the
  observation feeds. It tries the hand-picked `DARK_CANDIDATES` first, then buoys the catalog flags `met="n"`.
- `CHANGELOG.md` and `__version__` will conflict with the M1 and M3 pull requests; keep the newest release on top and
  the highest version.
