# Deferred

Ideas and findings that are real but outside the current milestone. Add one line each, with the milestone that found it,
and move an item into a milestone brief when it is scheduled.

## Post-0.8 candidates

- A second agency through the provider seam, starting with JTWC for the western Pacific and Indian Ocean.
- Model guidance ("spaghetti") from the ATCF a-deck files: OFCL and the main global and hurricane models on the map.
- Earliest and most-likely arrival-time layers from the KMZ products.
- Wind speed probability shading on the map.
- Operating-system notifications in addition to in-app toasts.
- Predicted tide overlay on the CO-OPS water level chart.
- Storm surge inundation GeoTIFFs (link-only for now).

## Found along the way

- M3: `Mode.HALF` (half-block glyphs) has no config value yet; `glyph_set` only offers unicode and ascii.
- M3: the best-track line and the dashed forecast can leave a gap when `storm.center` is newer than the last best-track point (`render/layers.py` `_draw_tracks`).
- M2: the October to December names of NDBC's monthly files are unknown until a month closes, so
  `ndbc.client.monthly_url` refuses them; check the real names and lift the limit.
- M4: `coops.water_level` defaults to MLLW and a Great Lakes gauge (`TideStation.great_lakes`) answers 400 for it, so the poller must pick the datum per gauge and catch the `HttpError` per gauge.
- M4: `TrackFix.hours` counts from the center's moment while the TCM counts from 3 h before the advisory, so M4 must subtract that offset when building fixes.
- M4: `trends.pressure_tendency` ignores its `hours` argument beyond PTDY and has no staleness check; the caller must not show a stale tendency.
- M1: parse the surge KML (`stormSurgeWatchWarningGIS`, `peakSurgeKML`) and the arrival-time KMZ files; M1 only keeps their URLs.
- M1: the best track zip also holds `radii` and `windswath` layers (observed wind field over the whole life); not parsed.
- M1: the NHC graphics landing page markup is unverified until a storm is active; revisit `providers/nhc/graphics.py` then.
- M1: match a gtwo outlook area to its invest b-deck; the zip carries probabilities but no invest id, so it is a position match.
- M1: `atcf/index/{AL,EP,CP}_storms.txt.nhc` and `master_list.txt` for id and name checks in replay tooling (M4).
- M4 poller: the GIS zip fetchers (`forecast_gis`, `fetch_forecast_gis`, `fetch_radii_gis`, `fetch_best_track_gis`, `outlook_gis`) always download the full zip; call them only when the advisory number changes, or add etag/last_modified.
- M4 poller: the api.weather.gov text fallback in `fetch_api_text`/`fetch_text` costs two unvalidated requests per product and runs on any 404 or empty tgftp body; gate it and use the list ETag.
- M4 alerts: ALERT_EVENTS includes "Extreme Wind Warning" and "Hurricane Force Wind Warning", which are not tropical-only; unverified against the live feed, filter in M4.
- M1 nits: import wrap_lon from providers.nhc.gis in current.py (move it to geo); no size cap on zip members in gis.py; no id dedupe in parse_current_storms.
