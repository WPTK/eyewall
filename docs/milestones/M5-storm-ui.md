# M5 Storm UI

## Goal

The Textual app with the dashboard, the map and the storm detail tabs, working in replay and live. Release 0.5.0.

## Depends on

M3 and M4 merged.

## Scope

Read the UI section of `docs/plan.md`. Adapt cfbtui's structure rather than inventing one; fetch what you need with
`gh api -H "Accept: application/vnd.github.raw+json" repos/WPTK/cfbtui/contents/<path>`: `cfbtui/ui/glyphs.py`,
`cfbtui/ui/theme.py`, `cfbtui/ui/app.tcss`, `cfbtui/ui/screens/help.py`, `cfbtui/app.py`.

- `app.py` and `ui/theme.py`, `ui/glyphs.py` (unicode and ascii sets), `ui/app.tcss`: the app starts the poller from M4 in a
  worker and updates widgets from its results; it runs against live or replay sources identically.
- Dashboard: `storm_list` grouped by basin (cyclones with a category-colored badge, wind, pressure, movement, advisory age;
  PTCs; invests with 2-day and 7-day chances; a quiet "No tropical cyclones" row per basin), `map_view`, `headline_panel`,
  `ww_panel`, `wind_panel`, `surge_panel`, and `status_bar` with per-feed freshness, the next poll and the replay transport
  (`space` pause, `<` `>` speed, `[` `]` previous and next advisory). Below 110 columns the side panels become tabs; below
  90 the map hides behind `m`.
- `map_view`: a Textual widget that renders M3's canvas through `render_line(y) -> Strip`; layer toggles, zoom, pan, fit to
  the cone, center on the storm. Buoys and tide gauges are drawn here too when M6 supplies them, so leave the hook.
- Storm detail screen (`Enter`): Summary, Forecast table, Public Advisory (TCP and TCM toggle), Discussion, Wind
  Probabilities, Watches and Warnings, History (best track). Buoys, Tides and Graphics tabs are placeholders for M6 and M7.
- Outlook screen: the TWO text per basin and a map of outlook areas hatched by risk. This and the watchlist table are the
  off-season default.
- Alert log screen, toasts from M4 events, help screen.
- Keys: the list in the plan's UI section, minus the ones that belong to M6 and M7.

## Out of scope

Buoy and tide tabs and charts (M6), images (M7), the settings screen (M6).

## Done when

- `python -m eyewall --replay demo` shows Erin: the list, the map with cone, track, forecast points, radii and
  warning segments, every storm tab, and a toast when you step to the next advisory.
- `python -m eyewall` live, on a quiet day, shows the outlook, invests if any, and "No tropical cyclones" rows without
  errors; pulling the network marks feeds stale rather than crashing.
- Pilot tests cover the main journeys over the replay bundle; snapshot tests pin the dashboard, a detail tab and the
  outlook.
- All checks in `CLAUDE.md` pass; version is 0.5.0 with its changelog entry; State after is filled in and the status in
  `docs/milestones/README.md` is updated. The README gains screenshots made with `scripts/screenshot_terminal.ps1`
  (adapt cfbtui's).

## Verify

The commands in `CLAUDE.md`, then run the replay and the live app in Windows Terminal and look at them, including at 80 by
24 and at 140 by 45.

## State after

(to be filled in by the session)
