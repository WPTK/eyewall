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

(to be filled in by the session)
