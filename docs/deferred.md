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

- M2: the October to December names of NDBC's monthly files are unknown until a month closes, so
  `ndbc.client.monthly_url` refuses them; check the real names and lift the limit.
- M4: `coops.water_level` defaults to MLLW and a Great Lakes gauge (`TideStation.great_lakes`) answers 400 for it, so the poller must pick the datum per gauge and catch the `HttpError` per gauge.
- M4: `TrackFix.hours` counts from the center's moment while the TCM counts from 3 h before the advisory, so M4 must subtract that offset when building fixes.
- M4: `trends.pressure_tendency` ignores its `hours` argument beyond PTDY and has no staleness check; the caller must not show a stale tendency.
