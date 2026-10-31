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

M3 is done. Its pull request carries the 0.3.0 version and changelog entry; nothing is tagged. 217 tests in `tests/test_render_*.py` cover it, with
golden text renderings in `tests/golden/`.

**What exists**

- `render/projection.py`: `Viewport` (center, degrees per dot, size in cells, dots per cell) with `to_dot`, `to_geo`,
  `dot_at`, `project_path`, `pan_dots`/`pan_cells`/`pan_degrees`, `zoom` (optionally about an anchor dot), `resized`,
  `centered_on`, `fit` and `fit_points`; `Bounds` and `bounds_of` take the shortest arc, so a view of 170 E to 170 W
  has a center of 180. Longitudes are always offsets from the view center, which is what makes the antimeridian work.
- `render/canvas.py`: `Canvas` in three modes (`BRAILLE` 2 by 4 dots per cell, `HALF` and `ASCII` 1 by 2). Lines with a
  dash pattern and a width of 2, polylines, arcs and circles, even-odd scanline fill with eight fixed shade patterns,
  a clip stack, text, markers, and a color per cell from the highest `Priority`. `rows_as_runs()` returns rows of
  `(text, Style(fg, bg, bold))`; `lines()` and `to_text()` return plain text.
- `render/basemap.py`, `mapdata/loader.py` and five `.bin` files (165 KB in all, `scripts/build_mapdata.py` builds them
  and `--check` proves they are current). 50 m data below 0.3 degrees per dot, 110 m above; state lines only at 50 m.
- `render/layers.py`: the inputs (`StormScene`, `TrackPoint`, `ForecastPoint`, `WarningSegment`, `WindRadii`,
  `OutlookArea`, `StationMark`, `MapScene`), `MapOptions`, `MapStyle`, `render_map()`, `draw_scene()` and
  `scene_bounds()`. Nothing in `render/` or `mapdata/` imports Textual or `models/`; a test enforces it.
- `render/chart.py`: `render_chart()` with `ChartSeries`, `Tick`, `ChartStyle`, nice ticks, a legend row, an optional grid
  and gaps for missing values.

**Deviations from the brief**

- `mapdata/land50.bin` (50 m land polygons, 62 KB) is vendored next to the 110 m land the brief lists. With only 110 m
  fill, the land stopped several dots short of or past the 50 m coastline at storm zoom levels. The total is still 165 KB.
- `tests/render_support.py` (the golden helper and the hand-built Erin-like storm) and `tests/golden/` sit outside the
  `tests/test_render_*.py` pattern the brief names; they exist only for these tests.
- `docs/plan.md`, `docs/data-sources.md` and `docs/deferred.md` got small edits (land50, pinned source, the renderer
  interface, three parked ideas).
- `MapOptions` has more switches than the `[map]` config section (outlook, warnings, track, buoys, tide gauges,
  labels, station labels), so the layer menu can toggle them. Only `land`, `borders`, `cone` and `radii` come from config.

**What the next sessions must know**

- M5 builds one `Viewport(lat, lon, deg_per_dot, cols, rows, mode.dots_x, mode.dots_y)` per widget size, calls
  `render_map(viewport, scene, mode, options)` and turns `canvas.rows_as_runs()` into `Strip`s
  (`Segment(text, Style(color=fg, bgcolor=bg, bold=bold))`). `[map] glyph_set = "ascii"` means `Mode.ASCII`. Mouse or
  cursor positions go back through `viewport.to_geo(x, y)`. Zoom keys are `viewport.zoom(2.0)` and `zoom(0.5)`, arrows are
  `pan_cells`, `c` is `centered_on` and `f` is `Viewport.fit_points(storm.extent(), ...)`.
- Wind radii are nautical miles in the order NE, SE, SW, NW, as the TCM lists them. Cone, outlook and warning geometry is
  `(lat, lon)`; shapefile readers return `(lon, lat)`, so swap them in the adapter.
- `basemap_canvas()` keeps the last eight rasters and always returns a copy, so drawing on the result is safe.
- Goldens: `EYEWALL_UPDATE_GOLDEN=1 python -m pytest tests/test_render_*.py` rewrites them; read the diff before committing.
  Everything that feeds a golden is built to give the same dots on Windows, Linux and macOS: the longitude scale is rounded
  to nine decimals, wind radii outlines to five, arcs to nine, and test data avoids trigonometry. If a golden ever fails on
  one operating system only, look for a coordinate sitting exactly on a dot boundary.
- The dot grid assumes a terminal cell about twice as tall as wide, so one degree per dot is the same in both directions.
- M8's PyInstaller spec must bundle `eyewall/mapdata/*.bin` as data files; `loader.py` reads them with
  `importlib.resources`.
- Lakes are filled as land and Mexican state lines are missing (see `docs/deferred.md`).
- The 0.3.0 changelog entry, `__version__` and the `deferred.md` list will conflict with the M1 and M2 pull requests;
  keep the releases newest first when merging.

