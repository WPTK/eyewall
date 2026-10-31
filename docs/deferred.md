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
- M2: the October to December names of NDBC's monthly files are still unverified: on 31 October 2026 the `data/stdmet/{Oct,Nov,Dec}/` directories were empty, `Sep/` held only the plain `{id}.txt` files and `Jan/`, `Jul/` and `Aug/` held `{id}{M}{yyyy}.txt.gz`. `ndbc.client.monthly_url` keeps refusing months 10 to 12; check the listings again once a month closes (October's file appears after the following month ends) and lift the limit then.
- M1: parse the surge KML (`stormSurgeWatchWarningGIS`, `peakSurgeKML`) and the arrival-time KMZ files; M1 only keeps their URLs.
- M1: the best track zip also holds `radii` and `windswath` layers (observed wind field over the whole life); not parsed.
- M1: the NHC graphics landing page markup is unverified until a storm is active; revisit `providers/nhc/graphics.py` then.
- M1: match a gtwo outlook area to its invest b-deck; the zip carries probabilities but no invest id, so it is a position match. Parked: nothing consumes an invest id on an outlook shape yet, so a matcher would be unused code; do it with the UI that needs it, and match only when exactly one invest lies inside one area.
- M1: `atcf/index/{AL,EP,CP}_storms.txt.nhc` and `master_list.txt` for id and name checks in replay tooling (M4).
- M4: the `GIS`-based best track (`best_track_gis`, with the observed wind field) is not fetched; the b-deck is the only best track source.
- M4: the poller fetches at most 24 buoy series and 12 tide gauges per poll, nearest first; the config has no key for it.
- M4: the "US threat" test for polling alerts is a pair of latitude and longitude boxes (Atlantic and Gulf coasts, Hawaii) plus any coastal watch or warning in effect; a land-geometry test would be exact.
- M4: the Erin demo bundle's best track starts at the first recorded advisory (06Z on 19 August), so the first three hours of the replay have no past track; re-record with a longer `--track-hours` if the track history matters.
- M4: the replay serves no outlook, invests, alerts or satellite; a bundle format for them is not worth recording until a UI needs them.
- M4: the replay source does not classify its feeds (outlook, alerts, satellite) the way the live source does, so a replay reports them as always fresh. Parked: a replay is never `stale` on purpose (a stale feed shows the status bar's `OFFLINE: cached data`, and `ui/format.py` is out of this change), and the honest answer is that the poller should skip feeds the source does not serve, which needs a new `DataSource` method.
- M5: README screenshots; `scripts/screenshot_terminal.ps1` needs a visible Windows Terminal, so take them by hand (M6 is in now).
- M5: the replay serves no outlook, so the outlook screen is only populated live.
- M5: only the current wind radii are drawn; the forecast radii at each forecast point are not.
- M5: surge geometry (KML) is not parsed, so the map has no surge lines and the surge panel shows text only.
- M5: on a quiet day the dashboard stays the first screen; opening on the outlook automatically is not done.
- M5: parsing runs on the UI loop with no `asyncio.to_thread`; measure a replay at 3600x for freezes before moving the sync parses off the loop.
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
- M7: the cone crop margins (`CONE_MARGINS` in `render/images.py`) were measured on the 2025 Erin cone only; check them against the next live cone and the `no_line` variants.
- M7: the gallery has no key to pick the image size (`500x500`, `2000x2000`) or a satellite band other than 13; the product list is fixed in `ui/gallery.py`.
- M7: a loop over 24 MB (a long storm's full GEOCOLOR loop) is refused with a message; fall back to the newest ranged loop instead. Parked: `FloaterProduct` keeps one `loop_url`, so the ranged loops have to be kept by `parse_floater_listing` in `providers/nhc/graphics.py` first.
- M7: the gallery cannot browse the archived per-advisory cones, so an earlier advisory's graphic is out of reach; the replay shows the newest one recorded.
- M7: Sixel and Kitty drawing, and the size of the picture inside its area, are not verified in a real terminal; see the State after of the M7 brief.
- M7: the settings screen has no widget for `[graphics] inline`; it stays in the TOML file.
- M7: the loop timer decodes each frame on the event loop (`Frames.frame`), and wrapping back to frame 0 makes Pillow re-decode the GIF from its start; decode ahead in a thread if a long loop stutters.
- M7: surge KML and arrival-time KMZ files are listed as link only; parsing them is still the M1 deferred item.
- #18: the map marks states by colour alone: station marks by reported wind and dimmed when stale, outlook areas by risk, watch and warning track segments by kind. The same facts are in text on the panels and tables; a glyph per state would need new marks on a braille canvas.
- #18: the buoy chart draws wind and gust as two lines told apart by colour alone (the legend names them); a dashed gust line would need a new line style in `render/chart.py`.
- #20: the dashboard map fit shows the whole five-day cone, so a storm that recurves (Erin at advisory 38 reaches 57 N) is fitted by its long extent and sits at one edge with empty bands above and below. Centring on the storm needs the fit to stop at the 72 hour point, which means a `tau` on the map's `ForecastPoint` and a decision about whether the cone may be cropped; the "Fit cone" key and help text promise the whole cone.
- Footer (#16): the outlook screen's footer shows `+/- zoom` and `fit` when its map is focused, and `esc back` stands in for `O`; its hard-coded `Enter: charts   w: edit` line above the watchlist remains.
- Footer (#16): `t` now works only on the Advisory tab (it used to jump there from any tab), and `p` does nothing off the Buoys and Tides tabs (the toast that explained it is gone).
- Footer (#16): `q`, `g`, `O`, `A`, `w`, `S`, `/`, `r`, `u` and the replay keys are in `?` help only; the snapshot tests pin the status line, so `tests/test_footer.py` checks the footer instead.
- Poller: the feeds are still polled one after another; `FEED_DEADLINE` bounds a hung host, but independent feeds (buoys, tides, satellite) could run concurrently. Parked: it changes the ordering the store and the alert engine rely on.
- Poller: when a new advisory arrives the old cone and wind radii are dropped (they carry their advisory number); the graphics links are not, because a graphics page lists intermediate advisories under their own numbers. They are refetched with the cone and retried like it.
- Cache: parsing a large body (the 1 MB NESDIS listing, the zips) still happens on the UI loop; only the disk reads, writes and the startup prune moved to a thread.
- `fetch_image` follows redirects itself; give `fetch_bytes` a per-hop URL check so the two can be one.
