# M3 Renderer and basemap

## Goal

Everything needed to draw a map and charts into a terminal, with no Textual in it, tested by golden text renderings.
Release 0.3.0.

## Depends on

M0. Runs at the same time as M1 and M2 in its own worktree. You own `src/eyewall/render/`, `src/eyewall/mapdata/`,
`scripts/build_mapdata.py` and `tests/test_render_*.py`. Do not import `textual` anywhere under `render/`. Do not depend on
M1's models: the layers take plain render-ready inputs defined in `render/layers.py`, and M5 adapts storm data to them.

## Scope

- `render/projection.py`: a viewport (center, degrees per dot, size in cells) with conversion in both directions between
  (lat, lon) and braille dot coordinates, an equirectangular projection scaled by the cosine of the center latitude, pan,
  zoom, and fit-to-bounding-box. It must handle the antimeridian, because Central Pacific storms cross it.
- `render/canvas.py`: a grid of terminal cells, each a 2 by 4 braille dot block (and a half-block mode with 1 by 2 dots for
  fonts with poor braille). Bresenham lines, polylines, circles and arcs, scanline polygon fill with a dotted shade,
  clipping, markers, text labels that overwrite cells, and a per-cell color with layer priority (track over warning over
  cone over coast). It outputs rows of (text, style) runs that a Textual widget can turn into a `Strip`. It also supports an
  ASCII fallback for the legacy Windows console.
- `render/basemap.py` and `mapdata/`: `scripts/build_mapdata.py` downloads Natural Earth GeoJSON from the nvkelso mirror
  (50 m coastline, 50 m admin-1 state lines, 50 m country boundaries, 110 m coastline and land), clips to the basin
  bounding box (about 100 E eastward across the Pacific to 10 W, 5 S to 60 N), simplifies with Douglas-Peucker, and packs
  int16 hundredths of a degree into `.bin` files with `ATTRIBUTION.md`. Keep the total under 600 KB. `mapdata/loader.py` reads
  them with `struct`; `basemap.py` picks a detail level for the zoom and caches the raster per viewport. The `.bin` files
  are committed.
- `render/layers.py`: draws in this order: land (dim fill), coastline, borders, cone (shaded fill with a bright edge),
  outlook areas (hatched by risk with probability labels), surge polylines, coastal watch and warning segments colored by
  `palette.WatchWarning`, best track colored by intensity, forecast line and points with `12Z Tue` labels, wind radii rings
  (34 kt dashed, 50, 64 solid), tide gauges, buoys colored by `palette.wind_band_color`, the storm center, a cursor. Define
  the input dataclasses here.
- `render/chart.py`: line charts with axes, ticks and multiple series on the same dot grid, for buoy pressure, wind and wave
  traces.

## Out of scope

The Textual widget (M5), storm data models, fetching anything.

## Done when

- Golden tests render the Gulf of Mexico and Caribbean recognisably into a 120 by 40 grid, and a cone, track, radii and
  warning segments from a hand-built Erin-like example. Projection round-trips and antimeridian cases are tested.
- Charts have golden tests for one and two series.
- `build_mapdata.py` is reproducible and its output is committed; all checks in `CLAUDE.md` pass; version is 0.3.0 with its
  changelog entry; State after is filled in and the status in `docs/milestones/README.md` is updated.

## Verify

The commands in `CLAUDE.md`. Also print one golden to the terminal and look at it.

## State after

(to be filled in by the session)
