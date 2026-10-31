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

(to be filled in by the session)
