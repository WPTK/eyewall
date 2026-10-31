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
- M6: a watchlisted gauge that is missing from the CO-OPS catalog shows "waiting" forever; say it is unknown.
- M8: CI binary builds install runtime dependencies unpinned (no lock file); lock them when a lock file exists.
- M8: binaries pass between jobs as artifacts, which drop the executable bit; the release uploads the files as built, so users `chmod +x`. Ship tar.gz archives if that bites.
- M8: the canary issue lists only `FAIL` lines; print the last 40 lines of a traceback too. GitHub disables scheduled workflows after 60 days without repository activity, so a quiet repo needs a manual dispatch now and then.
- M7: the cone crop margins (`CONE_MARGINS` in `render/images.py`) were measured on the 2025 Erin cone only; check them against the next live cone and the `no_line` variants.
- M7: the gallery has no key to pick the image size (`500x500`, `2000x2000`) or a satellite band other than 13; the product list is fixed in `ui/gallery.py`.
- M7: a loop over 24 MB (a long storm's full GEOCOLOR loop) is refused with a message; fall back to the newest ranged loop instead.
- M7: the download is read whole before the size check (the cache layer already caps a body at 32 MB); stream and abort on the first byte over the limit.
- M7: the gallery cannot browse the archived per-advisory cones, so an earlier advisory's graphic is out of reach; the replay shows the newest one recorded.
- M7: Sixel and Kitty drawing, and the size of the picture inside its area, are not verified in a real terminal; see the State after of the M7 brief.
- M7: the settings screen has no widget for `[graphics] inline`; it stays in the TOML file.
- M7: surge KML and arrival-time KMZ files are listed as link only; parsing them is still the M1 deferred item.
- M7: a GIF loop is decoded (frame count, first frame) on the event loop when it opens; move the decode to a thread like the stills.
- M7: `fetch_bytes` buffers the whole body before the 24 MB size check; check `Content-Length` and stream.
- M7: the gallery asks NESDIS for the same product listing from several panels; share one in-flight request.
- M7: the "is inline graphics possible" test is written twice (`run_app` and `GalleryPanel.uses_inline`); keep one predicate.
- #18: the map marks states by colour alone: station marks by reported wind and dimmed when stale, outlook areas by risk, watch and warning track segments by kind. The same facts are in text on the panels and tables; a glyph per state would need new marks on a braille canvas.
- #18: the buoy chart draws wind and gust as two lines told apart by colour alone (the legend names them); a dashed gust line would need a new line style in `render/chart.py`.
