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

**What exists.** Every storm-side NOAA feed parses into frozen dataclasses through pure functions, with an `NhcClient`
over `eyewall.net`. Nothing caches, polls or renders.

- `models/`: `storm.py` (`Storm`, `CurrentStorms`, `Classification`, `Basin`, `AdvNum`, `ProductRef`, `GisRef`),
  `forecast.py` (`ForecastAdvisory`, `ForecastFix`, `ForecastGis`), `advisory.py` (`PublicAdvisory`, `Discussion`,
  `AdvisorySet`, api product types), `wind.py` (`QuadrantRadii`, `WindRadii`, `WindProbabilities`, radii polygons),
  `watches.py`, `outlook.py`, `graphics.py`, and `track.py` (new, see below). `models/__init__.py` is still empty.
- `providers/base.py` (`StormProvider` protocol, `ParseError`) and `providers/nhc/`: `ids.py` (ids, bins, advisory
  numbers, every URL, `text_is_current`), `times.py`, `textutil.py`, `current.py`, `tcm.py`, `text.py` (TCP, TCD, PWS,
  TWO), `atcf.py` (b-decks and the `btk` listing), `gis.py` (forecast, radii and best track zips), `two.py` (gtwo zip),
  `alerts.py` (alerts and the api.weather.gov product fallback), `graphics.py` (landing page and NESDIS listings),
  `client.py`.
- `scripts/record_fixtures.py` (`record` for the committed set, `storm` for any archived storm) and
  `scripts/spot_check_nhc.py` (43 checks against the live services, about 20 s; passes on a quiet day).
- `tests/fixtures/nhc` and `tests/fixtures/gis`: 54 payloads (51 recorded, 3 hand-built) listed with URL, time and SHA-256 in
  `tests/fixtures/nhc/sources.json` (1.6 MB); 11 test modules (`tests/test_nhc_*.py`, plus the loader `tests/nhc_fixtures.py`) with
  330 tests, including hypothesis tests that damage real payloads and expect a result or `ParseError`.

**Deviations from the brief, and why.**

- **The odd-case fixtures are real recordings, not hand-built.** tgftp keeps the last advisory of the latest storm in each
  bin, and on 2026-10-31 those were post-tropical, remnant, dissipating, dateline and no-radii cases: Fay (post-tropical,
  `DISSIPATED`), Olana and Vance (no radii), Josephine (partial radii), Hurricane Nolo (an `ep` id in the CP2 bin, east
  longitudes, W and E in one product, a cone across the dateline), plus the 2024 Potential Tropical Cyclone Eight and the real
  `030A` intermediate zip for Erin. Only three fixtures are hand-built, each flagged in `sources.json`: the populated
  CurrentStorms file (no storm is active; modelled on the 2023 sample, edited to the live shape, with Erin at the
  intermediate 30A, a PTC, a post-tropical storm and Nolo in a CP bin), a populated alerts file (the alerts feed only serves
  active alerts; a real-shape file of frost and freeze alerts is recorded too), and a modelled graphics landing page.
- **Key messages come from the discussion.** The public advisory only says where to find them; `Discussion.key_messages`
  holds the list. `PublicAdvisory.key_messages` is filled only if a TCP carries a `KEY MESSAGES:` list.
- **Added `models/track.py`, `providers/nhc/times.py` and `textutil.py`.** Best track types did not fit the planned model
  files; the other two are shared helpers. The layout in `docs/plan.md` is updated.
- **The TWO in the plan's fixture list became three outlooks.** A 2026 TWO "with invests" does not exist as such: 2026
  outlooks name areas but carry no invest numbers (`(AL91)` is an optional suffix on an area title, parsed if present,
  never observed). The fixtures are the 2026-09-10 outlook with two numbered areas and active systems, the live
  2026-10-31 outlooks, and gtwo zips from 2025-09-19 (three areas) and 2026-10-31.
- **No ATCF index URLs.** `atcf/index/…` is replay tooling (M4); nothing in M1 needs it.
- Shared M0 modules are untouched. `docs/data-sources.md` and `docs/plan.md` are corrected where the feeds disagreed (below).

**What the next session must know.**

- **Two layers in `NhcClient`.** `fetch_*` methods accept `etag`/`last_modified` and return `Response(value, fetched,
  source)`; `value` is None on 304 or 404, `fetched` carries the validators and raw body for the cache. The provider
  methods (`storms`, `advisory`, `forecast_gis`, `track`, `outlook_text`, `outlook_gis`, `graphics`) return parsed values
  and turn a failed or stale product into None. Parsers also take plain text or bytes, so the replay source can use them
  on bundle files.
- **Staleness.** Use `ids.text_is_current(storm, ref, storm_id=…, adv_num=…)`, where `ref` is the product's own reference
  (`storm.public_advisory`...). The public advisory can be at `30A` while the forecast advisory is at `30`, so one storm
  number does not fit every product. `Storm.adv_num` prefers the forecast advisory.
- **Bins are not storms.** Key by `Storm.id`. `Storm.basin` is the id's basin and `Storm.bin_basin` the bin's; they differ
  for a storm in a CP bin. `ids.parse_bin(storm.bin_number)` gives the bin for text URLs.
- **Invests are not in CurrentStorms.** Find them with `fetch_bdeck_index()` (`BDeckFile.is_invest`, `modified`), then
  `fetch_bdeck(storm_id)`; a b-deck stays listed after a system dies, so judge recency by `modified` and the last fix.
  `BestTrack.is_invest` (90 to 99) and `is_training` (80 to 89) are provided. gtwo areas carry probabilities but no id, so
  matching an outlook area to an invest is a position match.
- **Longitudes.** Text products keep the sign NOAA printed (E is positive and `180.0E` is 180.0). GIS vertices are wrapped
  to (-180, 180]. NOAA's layers disagree across the dateline, so a ring that crosses it jumps between 180 and -180: unwrap
  against the map center before drawing. `gis.wrap_lon` is the helper.
- **Units.** `Storm.movement_speed_mph` is mph; `ForecastAdvisory.movement_speed_kt`, wind and radii are knots and nautical
  miles; `PublicAdvisory.summary` is mph. A b-deck `0` for wind, pressure, gusts, eye and radius of max wind is None.
- **TCM fix hours** count from `ForecastAdvisory.synoptic`; `forecast_fixes` are 12 to 72 h and `outlook_fixes` are 96 and
  120 h. A dissipating system ends in a fix with `dissipated` set and no position. The final advisory has `is_final`; its
  wind probability table is empty.
- **Heavy fetches.** A forecast zip is 40 KB, a radii zip 120 KB, a best track zip up to 600 KB, and a NESDIS product
  listing is over a megabyte for a long storm; fetch them on an advisory change or on demand. `fetch_floater_storms` and
  `fetch_floater_products` are small.
- **Unverified until a live storm** (marked in the code and the data-sources doc): the graphics landing page markup and its
  image URLs (the parser is deliberately loose and classifies by product name), the `stormSurgeWatchWarningGIS` and
  `potentialStormSurgeFloodingGIS` objects (parsed as `GisRef` with `kml_url`; nothing parses the KML yet), and tropical
  alerts with geometry (the parser is tested on the real alert shape and a hand-built tropical one).
- **Corrections to `docs/data-sources.md`:** tgftp names are `wtnt2{n}` and so on for bin `n`, not `wtnt21` for every bin;
  CP b-decks are `bcp…` files in `btk/` (the `cphc/` folder is stale); the gtwo zip is one combined product with
  `Atlantic`/`Pacific` labels and percent strings, and has no invest ids; the NESDIS listing layout; shapefile 9999 fills and
  the dateline disagreement; `peakSurgeKMLFile`; key messages live in the discussion.
- **Left for the coordinator.** `README.md` still says "version 0.0.1"; it is the same line every parallel milestone would
  change, so it was left alone. The `tests/nhc_fixtures.py` loader is shared by the NHC tests only.
- `record_fixtures.py storm <id> --adv N` records exactly the archive products a replay bundle needs (the four text
  products from the archive pages, both zips, the b-deck and the best track), so `record_storm.py` can reuse its recipes
  and `ids.archive_product_url`, `forecast_zip_url`, `bdeck_archive_url` and `best_track_zip_url`.
