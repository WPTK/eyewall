# M6 Observations UI

## Goal

Buoys and tide gauges in the interface: the nearest-buoys strip, the Buoys and Tides tabs, buoy detail charts, the
watchlist and the settings screen. Release 0.6.0.

## Depends on

M5 merged.

## Scope

- Buoys tab: a `DataTable` ordered by distance with ID, name, distance, bearing, wind, gust, pressure, three-hour change,
  wave height, water temperature, age and closest approach. Wind is colored at 34, 50 and 64 kt, falling pressure is
  flagged, silent stations are dimmed and marked "not reporting". `p` pins a station to the watchlist.
- Nearest-buoys strip on the dashboard: the five closest with wind, pressure and change.
- Buoy detail screen (`Enter` on a row): M3's braille line charts for pressure, wind with gust, and wave height over 24, 48
  and 72 hours (`Sparkline`s in the header), the latest observation table, and the interval minimum pressure and peak
  gust from the `.supl` file. The 72 hour range may need the 45-day file; fetch it only on demand.
- Tides tab: gauges near the storm with observed against predicted water level, the residual (the surge estimate), wind
  and pressure.
- Map: buoys and gauges drawn from the same data, colored by reported wind, dim when stale.
- Watchlist editing (add by id with a search over the station catalogs, remove, pin) and the settings screen for poll
  intervals, units, basins, nearby radii, alert rules and glyph set, saved to the TOML config.
- Unit preset cycling (`u`) and the `/` station search.

## Out of scope

Images and graphics (M7).

## Done when

- In replay, the Buoys tab ranks Erin's nearby stations correctly, thresholds color as expected, charts render for a
  station that saw the storm, and the Tides tab shows a residual for a nearby gauge.
- A dark buoy appears as "not reporting" rather than as an error.
- Settings changes round-trip through the config file; unit cycling changes every number on screen.
- Pilot and snapshot tests cover the new screens. All checks in `CLAUDE.md` pass; version is 0.6.0 with its changelog entry;
  State after is filled in and the status in `docs/milestones/README.md` is updated.

## Verify

The commands in `CLAUDE.md`, then the replay and a live run in Windows Terminal.

## State after

**What exists.**

- `ui/stations.py` (no Textual): the rows for the Buoys and Tides tables, wind banding at 34, 50 and 64 kt, the pressure
  change flags, the residual colors, the chart series, the latest-observation and extremes text, and the station search.
  `state/tides.py` holds the residual (observed minus the prediction for the same 6-minute moment) and the silent test.
- `ui/widgets/station_table.py` (`StationTable`, rebuilt only when text or style changes, cursor follows the station id)
  and `ui/widgets/chart_view.py` (M3's `render_chart` as a widget). The Buoys, Tides and outlook watchlist tables use them.
- Screens: `buoy_detail` (Sparklines, three braille charts over 24, 48 and 72 hours with `h`, latest observation, `.supl`
  extremes fetched once on demand, `p` pins), `watchlist` (`w`; `a` add, `d` remove), `search` (`/`; Enter opens a buoy,
  Ctrl+P pins), `settings` (`S`; Ctrl+S saves through `parse_config`, so a bad value blocks the save and is shown).
- `EyewallApp(config_path=...)`: `apply_config` updates the store, poller, alert rules, glyphs, map and units and saves the
  TOML (`cli.py` passes the config path; `--no-config` keeps changes for the run). `toggle_watch`, `poll_now`, `open_buoy`.
- Data: `TideSeries.predictions` (6-minute CO-OPS predictions, live and replay; the three Erin gauges were recorded once
  into `coops/*.predictions.json`), `DataSource.ndbc_supplemental`, and the poller polls the watchlist (and any buoy whose
  detail screen is open) with no storm, which closes the M5 quiet-day item.
- Map marks: buoys by reported wind, gauges by their wind, both dim when stale; with no storm the watchlist is drawn.
- Tests: `tests/test_ui_obs.py` (Pilot: both tabs, detail, range cycling, pinning, watchlist, search, settings, unit
  cycling, a quiet day), `tests/test_ui_stations.py`, snapshots for the Buoys tab, Tides tab, buoy detail, watchlist and
  settings.

**Deviations.**

- The 72 hour chart needs no 45-day fetch: the 5-day file the poller already reads covers it. Only `.supl` is on demand.
- The replay bundle has no `.supl` files, so replay extremes come from the regular rows and say so.
- Tide gauges have no detail screen; Enter on a gauge row does nothing and `p` pins it. The predicted tide overlay moved
  out of the post-0.8 list because the predictions now exist, but the chart is not built.
- `p` and Enter on the tabs need the table focused, so activating a tab moves focus to its station table (only for the
  Buoys and Tides tabs, which leaves the existing Forecast snapshot unchanged).
- The settings screen has no widget for the map layers or the alert thresholds; those stay in the TOML file.

**Next session must know.**

- Snapshots were generated on Windows. The status bar is pinned and toasts are cleared before the picture; if a CI system
  differs, look at the diff before regenerating.
- Replay tests move the clock with `into_the_storm` (in `tests/ui_support.py`) instead of one tick per advisory, which cost
  a full poll each time.
- Not viewed by a person: the app in Windows Terminal. It was driven through Pilot at 80x24 and 140x45.
