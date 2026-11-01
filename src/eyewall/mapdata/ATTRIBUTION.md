# Map data attribution

The `.bin` files in this directory are derived from [Natural Earth](https://www.naturalearthdata.com/) vector data,
which is in the public domain ("Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com").
No permission or credit is required; it is given here anyway.

The data was read from the [nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector) mirror at
commit `f1890d9f152c896d250a77557a5751a93d494776` (tag v5.1.2), at the 1:10 million scale. They are clipped to longitude 95 E eastward across the
Pacific to 5 W and latitude 10 S to 65 N, simplified with Douglas-Peucker (0.002 degrees for the full tier, 0.03 for
the `_lo` tier used by whole-basin views) and stored as 32-bit integers in ten-thousandths of a degree.

`places.bin` holds point features from the same mirror and commit (`ne_10m_populated_places_simple`), kept inside the
same area and ordered by scalerank then population.

| File | Content | Natural Earth source | Bytes |
|---|---|---|---|
| `coast.bin` | 10 m coastline with minor islands | `ne_10m_coastline, ne_10m_minor_islands_coastline` | 1,220,538 |
| `land.bin` | 10 m land polygons | `ne_10m_land` | 1,207,461 |
| `lakes.bin` | 10 m lakes | `ne_10m_lakes` | 409,947 |
| `borders.bin` | 10 m country boundaries and state or province lines | `ne_10m_admin_0_boundary_lines_land, ne_10m_admin_1_states_provinces_lines` | 795,885 |
| `coast_lo.bin` | coarse coastline for whole-basin views | `ne_10m_coastline, ne_10m_minor_islands_coastline` | 305,705 |
| `land_lo.bin` | coarse land polygons for whole-basin views | `ne_10m_land` | 293,949 |
| `lakes_lo.bin` | coarse lakes for whole-basin views | `ne_10m_lakes` | 87,507 |
| `places.bin` | populated places for map labels (scalerank 8 or better) | `ne_10m_populated_places_simple` | 69,138 |

Total: 4,390,130 bytes. The format is described at the top of `scripts/build_mapdata.py`.

## Rebuilding

`python scripts/build_mapdata.py` downloads the sources into `cache/naturalearth/` and rewrites these files and this
page; `--check` rebuilds in memory and fails if the committed files differ. The sources are verified against these
SHA-256 digests:

- `ne_10m_coastline`: `6f75ae0e0de157b14946e2255eb1f5486d9a13819032e26d4610852d296788f6`
- `ne_10m_minor_islands_coastline`: `d51fadaffc954e9e85671b0a2ecaba78b883dda1714640a173c151932fd1f2fb`
- `ne_10m_land`: `1ac90796408bc6ad6911d69448485d3c4dbf2190370080368a09976e1c9f7416`
- `ne_10m_lakes`: `2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9`
- `ne_10m_admin_0_boundary_lines_land`: `74d9c16229c095fde65943a9919e337682f044bcebccb120764f38edf3b70f4a`
- `ne_10m_admin_1_states_provinces_lines`: `1a1f30ccaaf4cc9c4bde34266f0b8cbb955d3a4cf254b756912255f2ec7c75b6`
- `ne_10m_populated_places_simple`: `fd3fa867a320cbd5c5b6bb5bc550afeec2939fb2cef688e508007282a55ac42f`
