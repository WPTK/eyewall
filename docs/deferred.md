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

- M3: Natural Earth 50 m has state lines only for nine countries, none for Mexico or the Caribbean; the 10 m admin-1
  lines would add them at some cost in size.
- M3: lakes are filled as land and have no shoreline (the Great Lakes, Lake Okeechobee); the Natural Earth
  lakes layer would hollow them out.
- M3: `Mode.HALF` (half-block glyphs) has no config value yet; `glyph_set` only offers unicode and ascii.
- M3: basemap `DETAIL_SWITCH=0.3` drops most Central Pacific atolls in whole-basin Pacific views, which use the 110 m data.
- M3: the map-data clip boxes cut land fill flat at 10W, 100E, 5S and 60N.
- M3: the best-track line and the dashed forecast can leave a gap when `storm.center` is newer than the last best-track point (`render/layers.py` `_draw_tracks`).
