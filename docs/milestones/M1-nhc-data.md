# M1 NHC data layer

## Goal

Turn every storm-side NOAA feed into frozen dataclasses through pure, tolerant parsers, backed by saved real payloads.
Release 0.1.0.

## Depends on

M0. Runs at the same time as M2 and M3 in its own worktree. You own `src/eyewall/models/` (except `obs.py`),
`src/eyewall/providers/`, `tests/fixtures/nhc/`, `tests/fixtures/gis/`, `tests/test_nhc_*.py`, `scripts/record_fixtures.py`
and `scripts/spot_check_nhc.py`. Do not edit the shared M0 modules unless something small is truly missing, and say so in
State after. Keep `models/__init__.py` empty and import from submodules.

## Scope

Read `docs/data-sources.md` first; it lists the URLs and the quirks each parser must handle.

- `providers/nhc/ids.py`: normalize `al052025` and `AL052025`; map bins (`AT1`..`CP5`) to tgftp and api.weather.gov names;
  build every URL in the data-sources doc; parse `advNum` values such as `018a` into (number, intermediate).
- `current.py`: CurrentStorms.json to `Storm`. Numbers arrive as strings. Keep `movement_speed` in mph and name the unit
  in the field. Classification becomes an enum (TD, STD, TS, HU, STS, PTC, PC, TY plus an unknown fallback). Product and GIS
  objects become small references with `adv_num`, `issued` and `url`; any of them may be null.
- `tcm.py`: the forecast/advisory text. Center, movement, pressure, max wind and gust, 34/50/64 kt radii by quadrant, the
  forecast fixes at 12 to 72 h, the outlook fixes at 96 and 120 h, and the dissipated, post-tropical and remnant-low
  suffixes. Valid times count from the synoptic time, three hours before the advisory.
- `text.py`: TCP headline, key messages and watch/warning blocks; TCD sections; the PWS probability table; TWO areas with
  their 48 hour and 7 day chances.
- `atcf.py`: b-deck lines, including invests (90 to 99) and the up-to-three lines per time that carry the radii. Longitudes
  can be east.
- `gis.py`: forecast, wind radii and best track zips read with `pyshp` straight from bytes. Layers `*_5day_pts`, `*_5day_lin`,
  `*_5day_pgn` (cone), `*_ww_wwlin` (TCWW codes), forecast radii. Intermediate advisories use an `A` suffix. Polygons and
  lines come out as lists of (lat, lon); tolerate missing layers.
- `two.py`: `gtwo_shapefiles.zip` to invest and outlook areas with `PROB2DAY`, `PROB7DAY` and the risk labels.
- `alerts.py`: api.weather.gov alerts for the tropical event types, and the product-by-bin fallback for text.
- `graphics.py`: links from the `forecastGraphics` landing page, and the NESDIS floater directory listing to the newest still
  and loop per product.
- `client.py`: an `NhcClient` that takes an `httpx.AsyncClient` and builds on `eyewall.net.fetch_bytes`. No caching or
  polling; those arrive in M4.
- `providers/base.py`: the provider protocol, the seam for another agency.
- `scripts/record_fixtures.py` records a storm's products from the NHC archive into `tests/fixtures/`.
  `scripts/spot_check_nhc.py` fetches every live NHC endpoint once and prints a summary; on a quiet day it must show empty
  storm lists without error.

Fixtures to record or build: Hurricane Erin (AL052025) advisories, including one with all radii and one late advisory with
fewer; the Erin 5day, fcst and best-track zips; the `bal052025` b-deck; a 2026 TWO with invests; a populated CurrentStorms
file modelled on `https://www.nhc.noaa.gov/productexamples/NHC_JSON_Sample.json` but hand-edited to the live shape
(lowercase ids, string numbers, `latitudeNumeric`, mph movement); and hand-made odd cases: no storms, a potential tropical
cyclone, a post-tropical storm, an `ep` id in a `CP` bin, a TCM with missing radii, `DISSIPATED`, an east longitude, an `A`
intermediate zip name.

## Out of scope

Caching, polling, the store, events, any rendering or UI, NDBC and CO-OPS.

## Done when

- Every fixture parses and tests assert specific values: cone ring count, TCWW codes, radii by quadrant, the east
  longitude, the intermediate suffix, string-to-number coercion.
- `python scripts/spot_check_nhc.py` succeeds against the live services.
- All checks in `CLAUDE.md` pass; version is 0.1.0 with its changelog entry; this brief's State after is filled in and the
  status in `docs/milestones/README.md` is updated.

## Verify

The commands in `CLAUDE.md`, plus the spot check.

## State after

(to be filled in by the session)
