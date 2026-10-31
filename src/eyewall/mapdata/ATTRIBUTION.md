# Map data attribution

The `.bin` files in this directory are derived from [Natural Earth](https://www.naturalearthdata.com/) vector data,
which is in the public domain ("Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com").
No permission or credit is required; it is given here anyway.

The data was read from the [nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector) mirror at
commit `f1890d9f152c896d250a77557a5751a93d494776` (tag v5.1.2), clipped to longitude 100 E eastward across the Pacific to 10 W and latitude 5 S to
60 N, simplified with Douglas-Peucker and stored as 16-bit integers in hundredths of a degree.

| File | Content | Natural Earth source | Bytes |
|---|---|---|---|
| `coast50.bin` | 50 m coastline | `ne_50m_coastline` | 64,621 |
| `coast110.bin` | 110 m coastline | `ne_110m_coastline` | 6,080 |
| `land50.bin` | 50 m land polygons | `ne_50m_land` | 62,362 |
| `land110.bin` | 110 m land polygons | `ne_110m_land` | 5,807 |
| `borders.bin` | 50 m country boundaries and state or province lines | `ne_50m_admin_0_boundary_lines_land, ne_50m_admin_1_states_provinces_lines` | 26,582 |

Total: 165,452 bytes. The format is described at the top of `scripts/build_mapdata.py`.

## Rebuilding

`python scripts/build_mapdata.py` downloads the sources into `cache/naturalearth/` and rewrites these files and this
page; `--check` rebuilds in memory and fails if the committed files differ. The sources are verified against these
SHA-256 digests:

- `ne_50m_coastline`: `271f1c4c1908312bac6b29d158ea1356544beafc129f260005300913aa5ea283`
- `ne_50m_land`: `e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b`
- `ne_50m_admin_0_boundary_lines_land`: `2faac4f6b34386f3d21b6e018cf151f241f00e5c936d44dd17d7d9bfb147fa48`
- `ne_50m_admin_1_states_provinces_lines`: `72cca93c850d412628a5da4bc5ebfe21ba4d376eb34611bde6b623ee73f0fdcf`
- `ne_110m_coastline`: `851f581ff5ffb844deed8ae1a9ce22e3c4bb3d74fa342cadb5d8e39b41ae7c3c`
- `ne_110m_land`: `9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`
