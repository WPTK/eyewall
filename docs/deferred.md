# Deferred

Ideas and findings that are real but outside the current milestone. Add one line each, with the milestone that found it,
and move an item into a milestone brief when it is scheduled.

## Post-0.8 candidates

- A second agency through the provider seam, starting with JTWC for the western Pacific and Indian Ocean.
- Model guidance ("spaghetti") from the ATCF a-deck files: OFCL and the main global and hurricane models on the map.
- Earliest and most-likely arrival-time layers from the KMZ products.
- Wind speed probability shading on the map.
- Operating-system notifications in addition to in-app toasts.
- Storm surge inundation GeoTIFFs (link-only for now).

## Found along the way

- M3: `Mode.HALF` (half-block glyphs) has no config value yet; `glyph_set` only offers unicode and ascii.
- M3: the best-track line and the dashed forecast can leave a gap when `storm.center` is newer than the last best-track point (`render/layers.py` `_draw_tracks`).
- M2: the October to December names of NDBC's monthly files are unknown until a month closes, so
  `ndbc.client.monthly_url` refuses them; check the real names and lift the limit.
- M1: parse the surge KML (`stormSurgeWatchWarningGIS`, `peakSurgeKML`) and the arrival-time KMZ files; M1 only keeps their URLs.
- M1: the best track zip also holds `radii` and `windswath` layers (observed wind field over the whole life); not parsed.
- M1: the NHC graphics landing page markup is unverified until a storm is active; revisit `providers/nhc/graphics.py` then.
- M1: match a gtwo outlook area to its invest b-deck; the zip carries probabilities but no invest id, so it is a position match.
- M1: `atcf/index/{AL,EP,CP}_storms.txt.nhc` and `master_list.txt` for id and name checks in replay tooling (M4).
- M1 nits: import wrap_lon from providers.nhc.gis in current.py (move it to geo); no size cap on zip members in gis.py; no id dedupe in parse_current_storms.
- M4: the `GIS`-based best track (`best_track_gis`, with the observed wind field) is not fetched; the b-deck is the only best track source.
- M4: `LiveSource.satellite` only asks for GEOCOLOR; the other NESDIS products and the loops wait for the graphics screen (M7).
- M4: the poller fetches at most 24 buoy series and 12 tide gauges per poll, nearest first; the config has no key for it.
- M4: the "US threat" test for polling alerts is a pair of latitude and longitude boxes (Atlantic and Gulf coasts, Hawaii) plus any coastal watch or warning in effect; a land-geometry test would be exact.
- M4: the Erin demo bundle's best track starts at the first recorded advisory (06Z on 19 August), so the first three hours of the replay have no past track; re-record with a longer `--track-hours` if the track history matters.
- M4: the replay serves no outlook, invests, alerts or satellite; a bundle format for them is not worth recording until a UI needs them.
- M4: `LiveSource.satellite` makes one listing request per storm per satellite poll; cache the listing across storms.
- M4: coming back from away mode makes every feed due at once (a burst of requests); stagger the first poll after the return.
- M4: the replay source does not classify its feeds (outlook, alerts, satellite) the way the live source does, so a replay reports them as always fresh.
- M5: README screenshots; `scripts/screenshot_terminal.ps1` needs a visible Windows Terminal, so take them by hand (M6 is in now).
- M5: the replay serves no outlook, so the outlook screen is only populated live.
- M5: only the current wind radii are drawn; the forecast radii at each forecast point are not.
- M5: surge geometry (KML) is not parsed, so the map has no surge lines and the surge panel shows text only.
- M5: on a quiet day the dashboard stays the first screen; opening on the outlook automatically is not done.
- M5: parsing runs on the UI loop with no `asyncio.to_thread`; measure a replay at 3600x for freezes before moving the sync parses off the loop.
- M5: the status bar crowds below 90 columns; drop segments by priority instead of truncating.
- M5: the snapshot tests depend on the platform's text rendering; pin the font metrics or compare structure instead.
- M5: the map widget invalidates and redraws the whole canvas on every scene change; cache the layers that did not change.
- M6: a tide gauge has no detail screen; Enter on a gauge row does nothing and `p` pins it. Observed against predicted
  would want its own chart.
- M6: the replay bundle has no `.supl` files, so the buoy detail shows "the recording has no supplemental file" and the
  extremes come from the regular rows; record the `.supl` files with `scripts/record_storm.py`.
- M6: the buoy charts cover 24, 48 and 72 hours from the 5 day NDBC file; longer ranges (the 45 day file) are not wired.
- M6: the settings screen edits poll intervals, units, glyph set, basins, nearby radii and alert rules; the map layers,
  the alert thresholds and the per-storm options still need the TOML file.
- M6: the watchlist holds 60 stations per kind, but series files are capped at 24 buoys (open pages first, then the storm's nearest; a watchlist-only buoy is read from `latest_obs`) and gauges at 12 (the storm's nearest first, then the watchlist), so a long gauge watchlist is only partly polled; rotate through it.
- M6: the tide gauge marks on the map are colored by the gauge's wind only; water level residual is not drawn on the map.
- M6: Ctrl+P in the search modal collides with Textual's command palette binding; pick another key for pinning.
- M6: a watchlisted gauge that is missing from the CO-OPS catalog shows "waiting" forever; say it is unknown.
