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

- M1: parse the surge KML (`stormSurgeWatchWarningGIS`, `peakSurgeKML`) and the arrival-time KMZ files; M1 only keeps their URLs.
- M1: the best track zip also holds `radii` and `windswath` layers (observed wind field over the whole life); not parsed.
- M1: the NHC graphics landing page markup is unverified until a storm is active; revisit `providers/nhc/graphics.py` then.
- M1: match a gtwo outlook area to its invest b-deck; the zip carries probabilities but no invest id, so it is a position match.
- M1: `atcf/index/{AL,EP,CP}_storms.txt.nhc` and `master_list.txt` for id and name checks in replay tooling (M4).
