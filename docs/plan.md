# eyewall plan

This is the durable design for eyewall. `CLAUDE.md` holds the working rules, `docs/data-sources.md` the verified
feed details, and `docs/milestones/` one brief per implementation session. If the design changes, change it here in the
same pull request.

eyewall is a Textual terminal app that tracks active tropical cyclones, invests and potential tropical cyclones in the
Atlantic, East Pacific and Central Pacific from NOAA data. It draws tracks, cones, watches and warnings on a braille map,
shows advisories, discussions, wind radii and probabilities, surge information and NOAA graphics (inline images where the
terminal allows), shows live NDBC buoy and CO-OPS tide-gauge observations near each storm, and raises in-app alerts when
NOAA posts something new. It is useful off-season through the outlook view and a watchlist of buoys, and it has a replay
mode driven by a recorded past storm (Hurricane Erin, 2025).

## Key decisions

| Topic | Decision |
|---|---|
| Stack | Python 3.12 or newer, Textual 8, httpx; conventions follow the author's cfbtui project |
| Build | hatchling, `src/` layout, plain `pip` and `venv` commands (nothing here needs a specific tool, so uv works too) |
| Models | frozen dataclasses; tolerant parsers do the coercion NOAA's loosely typed feeds need |
| Storm geometry | the real NHC shapefiles (cone, forecast points, watch/warning lines, wind radii) read with pyshp |
| Text products | tgftp raw text first; api.weather.gov by storm bin (`AT1`, `EP2`, ...) as the fallback |
| Change detection | `lastUpdate` and `advNum` in CurrentStorms.json; the RSS feeds are not used |
| Releases | ZeroVer, one release per milestone, Common Changelog (see `CLAUDE.md`) |
| Delivery | one fresh working session per milestone, briefed from `docs/milestones/` |

## Repo layout

```
eyewall/
  pyproject.toml  README.md  CHANGELOG.md  CLAUDE.md  LICENSE  .gitignore  .gitattributes  eyewall.spec (M8)
  .github/workflows/ci.yml        ruff, vulture, mypy, pytest -n auto, --version; windows/ubuntu/macos × 3.12, 3.13
  .github/workflows/release.yml   on v* tag: version == tag == changelog heading; wheel + sdist (+ binaries from M8)
  .github/workflows/canary.yml    weekly: fetch every live endpoint once, run the parsers (M8)
  docs/plan.md                    this plan's Architecture, UI, Map and Graphics sections (the durable copy)
  docs/data-sources.md            the tables and facts above
  docs/milestones/M1-nhc-data.md … M8-release.md     one self-contained brief per session
  docs/deferred.md  docs/development.md  docs/replay.md  docs/img/
  scripts/build_mapdata.py  record_storm.py  record_fixtures.py  spot_check_nhc.py  spot_check_obs.py  record_obs_fixtures.py  screenshot_terminal.ps1  build_exe.ps1
  src/eyewall/
    __init__.py  __main__.py  cli.py  app.py  config.py  poll.py  units.py  geo.py  clock.py  palette.py  net.py
    models/     storm.py forecast.py advisory.py watches.py outlook.py wind.py graphics.py track.py obs.py events.py
    providers/  base.py (Provider protocol, the JTWC seam)
    providers/nhc/  client.py current.py tcm.py text.py atcf.py gis.py two.py alerts.py graphics.py ids.py times.py textutil.py
    ndbc/       client.py stations.py latest.py stdmet.py supl.py spec.py historical.py
    coops/      client.py stations.py data.py
    sources/    protocol.py live.py replay.py cache.py
    state/      store.py nearby.py trends.py events.py alerts.py
    render/     projection.py canvas.py basemap.py layers.py chart.py images.py text.py
    mapdata/    coast.bin land.bin lakes.bin borders.bin coast_lo.bin land_lo.bin lakes_lo.bin loader.py ATTRIBUTION.md
    ui/         app.tcss theme.py glyphs.py
    ui/screens/ dashboard.py storm_detail.py outlook.py buoy_detail.py graphics.py alert_log.py help.py settings.py
    ui/widgets/ storm_list.py map_view.py headline_panel.py ww_panel.py wind_panel.py surge_panel.py
                buoy_table.py tide_table.py obs_chart.py forecast_table.py text_viewer.py gallery.py status_bar.py
  tests/      conftest.py fakes.py fixtures/{nhc,ndbc,coops,gis,replay/erin2025}/ test_*.py uat/ __snapshots__/
```

## Architecture

**One `DataSource` protocol, two implementations.** `sources/protocol.py` declares the async methods the app
depends on (`storms()`, `advisory(id)`, `forecast_gis(id)`, `track(id)`, `outlook()`, `alerts()`,
`graphics(id)`, `ndbc_stations()`, `ndbc_latest()`, `ndbc_series(id, days)`, `coops_stations()`,
`coops_series(id)`, `now()`). `live.py` fetches through `cache.py`; `replay.py` serves a recorded bundle on a
virtual clock. Store, poller and UI cannot tell them apart.

**Parsers are pure and tolerant.** Every parser takes `str`/`bytes` and returns frozen dataclasses from
`models/`; unknown columns ignored, bad rows skipped and counted, `MM`/fills → `None`, strings coerced where
NHC serves numbers as strings. Each has fixtures for the odd cases listed above.

**Identity.** `providers/nhc/ids.py` normalizes `al052025` ↔ `AL052025`, maps bins to tgftp and api.weather.gov
names, pairs `advNum` with `lastUpdate` so stale text is never applied to a live storm.

Saffir-Simpson categories and every display color live in `palette.py` (`category_for_knots`, `Category`, `WatchWarning`); `units.py` converts and formats; `net.py` is the one HTTP helper (User-Agent, conditional GET, retries) that every provider builds on.

**State.** `state/store.py` holds storms (advisory, forecast, GIS layers, best track, WW, graphics links),
invests/outlook, station catalogs, latest obs, watched series. Derived:

- `state/nearby.py`: station included when distance to current center ≤ `radius_now_nm` (300) **or** to the
  forecast track polyline (interpolated hourly through `track_hours`, 72) ≤ `radius_track_nm` (150);
  watchlist always included; ranked by distance, capped at `max_stations` (40); closest approach + ETA.
- `state/trends.py`: 3 h pressure tendency (PTDY or from series), wind trend, obs age, "silent", `.supl`
  interval minimum pressure / peak gust.
- `state/events.py` + `state/alerts.py`: diff successive states into events (new storm/PTC/invest, new
  advisory incl. intermediates, classification change, WW issued/changed/discontinued, new TWO, new
  discussion, nearby buoy crossing 34/50/64 kt, buoy gone silent); alert rules from config; dedupe by
  (storm id, advNum, kind) **persisted** in `user_data_dir` so restarts do not re-fire; toasts + Alert Log.

**Polling.** `poll.py` adapts cfbtui's `PollScheduler` (freshness model, injectable clock, backoff, `refresh()`
wake, presence) to feeds with their own intervals: `storms` 300 s, `outlook` 1800 s, `alerts` 300 s while a
US threat exists, `buoys` 600 s (latest_obs then nearby 5-day files, staggered), `tides` 360 s, `satellite`
600 s. Text, GIS zips, b-decks and graphics refetch only when `advNum`/`lastUpdate` changes. Away mode (no
input for `away_after` s) triples intervals. Status bar shows per-feed age and the next poll.

**Geometry and rendering.** `geo.py`: haversine, bearing, destination point, point-to-segment distance,
dateline wrap. `render/projection.py`: viewport ↔ braille dots, equirectangular scaled by cos(center lat),
pan/zoom/fit. `render/canvas.py`: 2×4-dot braille grid plus a 1×2 half-block mode, Bresenham lines,
polylines, circles/arcs, **scanline polygon fill with dotted shade** (cone, land, invest areas), clipping,
markers, labels, per-cell color with layer priority (track > WW > cone > coast). `render/basemap.py` loads the
vendored polylines and caches the raster per viewport. `render/layers.py` draws, in order: land (dim fill),
coastline, borders, cone (shaded fill + bright edge), invest areas (hatched by risk, probability labels),
surge WW polylines, coastal WW segments colored by TCWW, best track colored by intensity, forecast line and
points (category color, `12Z Tue` labels), wind radii rings (34 dashed, 50, 64), tide gauges `▲`, buoys `●`
(colored by reported wind, dim when stale), storm center glyph, cursor. `render/chart.py` builds line charts
with axes on the same grid. `palette.py` is the NHC-standard palette: TD blue, TS green, Cat 1 yellow, Cat 2
orange, Cat 3 red, Cat 4 magenta, Cat 5 purple; TS watch yellow, TS warning blue, hurricane watch pink,
hurricane warning red; surge watch lavender, warning purple; invest risk low yellow / medium orange / high
red. `ui/widgets/map_view.py` renders rows via Textual's `render_line(y) -> Strip` API.

**Map data.** `scripts/build_mapdata.py` downloads the Natural Earth 1:10 million GeoJSON (coastline with minor
islands, land, lakes, country boundaries and admin-1 state lines), clips to the basins' bbox plus a 5° margin
(about 95°E eastward across the Pacific to 5°W, 10°S–65°N), simplifies (Douglas–Peucker 0.002° for the full tier,
0.03° for the `_lo` tier), packs polylines/polygons as int32 ten-thousandths of a degree into `mapdata/*.bin`
(about 4.3 MB, size is not a constraint; the map must never be oversimplified) with `ATTRIBUTION.md` (public
domain); `loader.py` reads with `struct`. Checked in. Long lines and land fill are cut into pieces so a viewport
only projects what it can see.
The download is pinned to one commit of the mirror and verified by SHA-256, so a rebuild is byte for byte the
same (`--check` confirms it). Every view draws the full 10 m tier except basin-scale views (`DETAIL_SWITCH`, 0.3°
per dot or coarser), which draw the `_lo` copy of the same data (every island kept) because the full tier takes about half a
second there. Lakes are holes in the land fill with their own shoreline; country boundaries and state lines share
`borders.bin`, and state lines show only in detailed views.

**Renderer interface.** `render/layers.py` defines its own render-ready inputs (`StormScene` with track, forecast,
cone rings, warning segments and wind radii in nautical miles by quadrant; `OutlookArea`; `StationMark`;
`MapScene`), so the UI adapts models to them and the renderer never imports `models/`. `render_map(viewport, scene,
mode, options, style)` returns a `Canvas`; `canvas.rows_as_runs()` gives rows of `(text, Style(fg, bg, bold))`
that `ui/widgets/map_view.py` turns into `Strip`s. The canvas modes are braille (2×4 dots per cell), half-block and
ASCII (both 1×2); the config's `glyph_set = "ascii"` selects ASCII. `render/chart.py` draws on the same canvas.

**Images.** `render/images.py`: fetch PNG/GIF/JPG → Pillow; `textual-image` picks Kitty/iTerm2/Sixel when
the terminal supports it (Windows Terminal ≥1.22 has Sixel); otherwise a readable fallback: LANCZOS
downsample to the cell grid ×2 (half-block) or ×(2,4) (braille), mild unsharp mask, auto-contrast, quantize to
the terminal's color depth, and for NHC cone graphics crop known margins so legends do not waste cells. GIFs:
extract frames, cap at 10 fps when inline, step with `[`/`]` in fallback. Always show the URL; `o` opens it in
the browser, `y` copies it (Textual's OSC 52 clipboard).

**Units.** `units.py`: kt/mph/km/h/m/s, mb/inHg, m/ft, nm/km/mi, °C/°F; presets `nautical` (kt, mb, nm, ft,
°F), `us`, `metric`.

**Config** (`config.py`, cfbtui's tolerant TOML loader under `user_config_dir("eyewall")`; flags override, never
write back):

```toml
[poll]      storms = 300  outlook = 1800  alerts = 300  buoys = 600  tides = 360  satellite = 600  backoff_max = 1800  away_after = 300
[basins]    enabled = ["AL", "EP", "CP"]
[nearby]    radius_now_nm = 300  radius_track_nm = 150  track_hours = 72  max_stations = 40
[units]     preset = "nautical"
[watchlist] ndbc = ["41010", "42001"]  coops = ["8721604"]
[map]       land = true  borders = true  cone = true  radii = true  glyph_set = "unicode"   # ascii for conhost
[alerts]    new_advisory = true  classification = true  watches_warnings = true  outlook = true  buoy_thresholds = true  bell = false
[graphics]  inline = "auto"   # auto | never
```

**Replay.** A bundle directory: `manifest.toml`, `atcf/b*.dat`, `nhc/<storm>/<advNum>.{tcm,tcp,tcd}.txt`,
`gis/<storm>/<advNum>_5day.zip`, `_fcst.zip`, `ndbc/activestations.xml`, `ndbc/<station>.stdmet.txt`,
`coops/<station>.*.json`, `graphics/` (a few stills). `ReplaySource` holds a virtual clock; at time *T* it
synthesizes CurrentStorms from the b-deck plus the latest advisory ≤ *T*, and latest_obs from each series'
rows ≤ *T*. Keys: `space` pause, `<`/`>` speed, `[`/`]` previous/next advisory.
`scripts/record_storm.py AL052025 --from 2025-08-15 --to 2025-08-23 --stations auto` builds one from the NHC
archive pages, `gis/forecast/archive/al052025_*`, `atcf/archive/2025/bal052025.dat.gz`,
`data/stdmet/Aug/{id}82025.txt.gz` and CO-OPS ranges. `tests/fixtures/replay/erin2025/` is trimmed (3 days,
~8 stations, 2 graphics) for tests and `eyewall --replay demo`. Erin tracked past 41047, 41048, 41010,
41002 and 41025 as a major hurricane, which exercises every panel.

## UI

**Dashboard** (default): left `storm_list` grouped by basin: cyclones (name, class badge in category color,
wind kt/mph, pressure, movement, advisory age), PTCs, invests with 2-day/7-day probabilities, and a quiet
"No tropical cyclones" row per basin. Center `map_view` fitted to the selected storm's cone (or the basin),
legend bar below. Right: `headline_panel` (latest headline, key messages), `ww_panel` (watches/warnings by
area with color chips; NWS zone alerts when US land is involved), `wind_panel` (max wind, gusts, radii per
quadrant, top 34/50/64 kt probabilities), `surge_panel` (surge WW areas, peak surge text from TCP), and a
**nearest buoys** strip (five closest with wind/pressure/ΔP). Bottom `status_bar`: per-feed freshness, next
poll, offline/stale, alert count, replay transport. Below 110 columns the side panels collapse into tabs;
below 90 the map hides behind `m`.

**Storm detail** (`Enter`): tabs Summary · Forecast (TAU, valid Z + local, lat/lon, wind, category) ·
**Buoys** (DataTable by distance: ID, name, dist, bearing, wind, gust, pres, ΔP 3h, wave, WTMP, age, closest
approach; thresholds colored; `p` pins; `Enter` → **buoy_detail** with braille charts of pressure, wind+gust,
wave over 24/48/72 h, `Sparkline`s, `.supl` minima) · **Tides** (gauges near the storm: observed vs predicted,
residual, wind, pressure) · Public Advisory · Forecast Advisory · Discussion · Wind Probs (PWS table) ·
Watches/Warnings · Graphics · History (best track table).

**Outlook**: TWO text per basin + map of invest areas hatched by risk with probabilities. The off-season
default view, together with the watchlist buoy table.

**Graphics**: gallery of `GraphicLink`s (cone PNG/GIF, wind probabilities 34/50/64, arrival time, surge WW,
peak surge, NESDIS GEOCOLOR/IR still and newest loop); inline image or pretty fallback plus URL; `o` open,
`y` copy, `[`/`]` frames.

**Alert Log**, **Help**, **Settings** (poll, units, basins, watchlist, alert rules, glyph set; saves TOML).

Keys: `j`/`k` select, `Enter` detail, `Tab` cycle panels, `1`/`2`/`3` basins, `a` all basins, `m` map
toggle, `M` full-screen map, `l` layer menu, `+`/`-` zoom, arrows pan, `c` center storm, `f` fit cone,
`b` buoys tab, `g` graphics, `t` text products, `A` alert log, `O` outlook, `r` refresh, `u` units preset,
`/` station search, `?` help, `q` quit.

## Milestones, one session each

```
M0 scaffold (done)
 ├─► M1 NHC data ──────────┐
 ├─► M2 observations data ─┼─► M4 core ─► M5 storm UI ─► M6 observations UI ─► M7 graphics ─► M8 release
 └─► M3 renderer + basemap ┘ (M3 feeds M5 directly)
```

M1, M2 and M3 run at the same time in separate worktrees (disjoint directories: `providers/nhc` + `models`;
`ndbc` + `coops` + `models/obs.py` + `state/nearby.py` + `state/trends.py`; `render` + `mapdata` + `scripts/build_mapdata.py`). Everything after runs in
order. Each brief at `docs/milestones/Mn-<slug>.md` has the same headings: **Goal**, **Depends on**,
**Scope**, **Out of scope**, **Done when**, **Verify**, **State after** (filled by the session). A milestone
session is started with one line: "Implement milestone Mn of this repo per
`docs/milestones/Mn-<slug>.md`; branch `mN-<slug>`, PR to `main`, CI green, release `0.N.0`."

| M | Scope | Release | Done when |
|---|---|---|---|
| **M0 Scaffold and handoff** (straight to `main`) | Repository and packaging, `ci.yml` and `release.yml`, `CLAUDE.md`, the shared modules every later milestone imports (`config`, `units`, `geo`, `clock`, `palette`, `net`, a `cli` stub), empty subpackages so parallel milestones never collide, `docs/`, and the milestone briefs | 0.0.1 (no tag) | CI green on 3 OSes; `python -m eyewall --version` prints `0.0.1`; a fresh session can start M1, M2 or M3 from the repo alone |
| **M1 NHC data layer** | `providers/nhc/*` + `models/*`: CurrentStorms, tgftp TCM/TCP/TCD/TWO/PWS parsers, api.weather.gov fallback and alerts, ATCF b-deck (incl. invests), GIS zips via pyshp (5day pts/lin/pgn, ww, fcst radii, best track), gtwo shapefiles, graphics landing page + NESDIS listing; `scripts/record_fixtures.py`; fixtures from Erin 2025 and a 2026 TWO with invests, plus the odd cases (no storms, PTC, post-tropical, `ep` id in CP bin, missing radii, `DISSIPATED`, `E` longitude, `A` intermediate zip); `scripts/spot_check_nhc.py` | 0.1.0 | all fixtures parse; `spot_check_nhc.py` parses every live NHC endpoint; cone polygon ring count and WW TCWW codes asserted |
| **M2 Observations data layer** | `ndbc/*`, `coops/*`, `state/nearby.py`, `state/trends.py` (pure); fixtures (`MM` rows, 9-fills, 404 station, `""` gaps); `scripts/spot_check_obs.py`, `scripts/record_obs_fixtures.py` | 0.2.0 | parsers and nearby/trends tests pass; spot check parses live NDBC/CO-OPS incl. a dark buoy as "not reporting" |
| **M3 Renderer and basemap** | `render/projection.py`, `canvas.py` (braille + half-block, fill, clip), `basemap.py`, `layers.py`, `chart.py`, `scripts/build_mapdata.py`, vendored `mapdata/`; ASCII golden tests | 0.3.0 | Gulf and Caribbean recognisable in a 120×40 golden; cone fill and WW segments render from an Erin GIS fixture |
| **M4 Core** | `sources/{protocol,live,cache,replay}.py`, `poll.py`, `state/{store,events,alerts}.py`, `scripts/record_storm.py` + Erin bundle, `--replay`/`--demo`, headless `--until` helper | 0.4.0 | `eyewall --replay demo --headless --until +12h` logs the expected advisory, WW and buoy events; persisted dedupe survives a restart |
| **M5 Storm UI** | `app.py`, theme, glyphs, dashboard (list, map, panels, status bar), storm detail tabs (Summary, Forecast, advisories, discussion, Wind Probs, WW, History), outlook screen, alert log, help; pilot + snapshot tests over the replay bundle | 0.5.0 | every storm tab works in replay; toasts fire on advisory steps; live run shows outlook + "No tropical cyclones" rows |
| **M6 Observations UI** | Buoys and Tides tabs, nearest-buoys strip, `buoy_detail` charts, watchlist editing, settings screen, unit cycling | 0.6.0 | buoy table ranks and colors correctly in replay; charts render; settings round-trip TOML |
| **M7 Graphics** | `render/images.py`, `textual-image` wiring, pretty fallback, GIF stepping, gallery screen, open/copy URL | 0.7.0 | inline cone and GEOCOLOR images in Windows Terminal; readable fallback with `--glyphs ascii`; URL open/copy work |
| **M8 Polish and release** | README with screenshots, `docs/replay.md`, `canary.yml`, PyInstaller `eyewall.spec` + `build_exe.ps1` + binaries in `release.yml`, offline/first-run polish, smoke-test doc | 0.8.0 | `dist\eyewall.exe --replay demo` runs on a Windows machine; release has wheel, sdist, binaries, SHA256SUMS |
| Stretch (0.9+) | JTWC provider, a-deck model spaghetti, arrival-time KMZ layer, WSP probability shading, OS notifications, CO-OPS predictions overlay | | |

## Reuse from cfbtui (same owner; copy and adapt)

`poll.py` (freshness, backoff, presence), `config.py` loader pattern, `ui/glyphs.py`, `theme.py`, `app.tcss`
structure, `screens/help.py`, `screens/settings.py`, `pyproject` tool config, `ci.yml`, `release.yml`,
`espn-canary.yml` shape, `.gitattributes` fixture rule, `CLAUDE.md` shape, `scripts/*.ps1`.

## Verification

**M0:** CI green on Windows, Linux and macOS; `python -m eyewall --version` prints `0.0.1`;
tests cover `config`, `units`, `geo`, `clock`, `palette`; `docs/milestones/` has nine briefs (M0 to M8) with the seven
headings; `CLAUDE.md` states the no-attribution, ZeroVer, Common Changelog, Conventional Commits, PR-flow and
one-session-per-milestone rules; `CHANGELOG.md` is the heading only.

**Whole project (checked milestone by milestone, each in its own session):**

- `python -m ruff check .`, `python -m vulture src scripts --min-confidence 80`, `python -m mypy src`,
  `python -m pytest -n auto` green locally (Windows) and in CI.
- Parser tests cover every fixture; Hypothesis round-trips for `units` and `geo`; golden tests for the canvas,
  layers and charts; `nearby` tested against hand-computed distances.
- `eyewall --replay demo`: storm list shows Erin; map draws land, coast, cone fill, track, forecast points,
  radii, WW segments and buoys; `]` steps advisories and panels update with a toast; buoy table ranks by
  distance and colors thresholds; buoy detail charts render; graphics gallery shows the bundled stills;
  snapshot tests pin these screens.
- `python scripts/spot_check_nhc.py` and `scripts/spot_check_obs.py` against live NOAA: every endpoint fetched once, parsed, summarized;
  `canary.yml` runs it weekly to catch format drift.
- Live `eyewall` on a quiet day: outlook text, invest areas (if any), "No tropical cyclones" rows, watchlist
  buoys with correct ages; pulling the network marks feeds stale, not crashed.
- `python -m eyewall --version` and a fresh `pip install .` into a clean venv work.

## Risks

- **Textual 8 API assumptions** (`render_line`/`Strip`, `Sparkline`, `TabbedContent`, snapshot plugin
  support): verify in M0, adapt in M5. `pytest-textual-snapshot` lagging Textual 8 → in-house SVG snapshot
  fallback via `App.save_screenshot`.
- **No live storms until next season:** every feature is built and tested on the Erin bundle and fixtures;
  the graphics URL patterns and `storms.js`-style behaviours are confirmed during the first live storm, with
  `canary.yml` watching for drift meanwhile.
- **Shapefile and KML variability:** parse by field name, tolerate missing layers, keep TCM text as the
  numeric truth so the map degrades to text-derived radii if a zip is missing.
- **Inline images on Windows:** Sixel needs Windows Terminal ≥1.22; the fallback path is first-class, not an
  afterthought, and `graphics.inline = "never"` forces it.
- **Session hand-off drift:** `docs/plan.md` and the milestone briefs are the single source; each session
  records deviations in its brief's "State after" section; the coordinating session reads the merged diff
  before starting the next one.
