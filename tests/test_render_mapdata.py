"""The vendored map data and the script that builds it. Nothing here touches the network."""

import hashlib
import importlib.util
import itertools
import json
import math
import struct
import sys
from pathlib import Path

import pytest

from eyewall.mapdata import loader

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_mapdata.py"
DATA_DIR = Path(loader.__file__).parent


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("build_mapdata", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_mapdata"] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("build_mapdata", None)


def near(layer, lat, lon, tolerance=0.15):
    """Whether any vertex of the layer is within tolerance degrees of a place."""
    return any(
        abs(p[0] - lat) <= tolerance and abs(p[1] - lon) <= tolerance for path in layer.paths for p in path.points
    )


# ------------------------------------------------------------------------------------------------ committed files


def test_the_committed_data_is_not_oversimplified():
    """Floors that fail if the base map silently drops back to the 1:50 million detail it replaced (the old
    coastline had about 16,000 vertices in this box; the 10 m data has about 150,000)."""
    assert loader.load_layer("coast").vertex_count >= 120_000
    assert loader.load_layer("land").vertex_count >= 120_000
    assert loader.load_layer("lakes").vertex_count >= 40_000
    assert loader.load_layer("borders").vertex_count >= 70_000
    assert sum((DATA_DIR / f"{name}.bin").stat().st_size for name in loader.LAYERS) > 3_000_000


def count_vertices(layer, south, west, north, east):
    return sum(1 for path in layer.paths for lat, lon in path.points if south <= lat <= north and west <= lon <= east)


@pytest.mark.parametrize(
    ("name", "box", "floor"),
    [
        ("Florida Keys and the Florida coast", (24.0, -83.0, 26.0, -80.0), 400),
        ("Outer Banks", (34.7, -76.9, 36.9, -75.2), 400),
        ("Louisiana and Mississippi coast", (28.0, -95.0, 31.0, -88.0), 800),
        ("Majuro atoll", (6.8, 170.8, 7.4, 171.6), 12),
        ("Tarawa atoll", (1.2, 172.8, 1.8, 173.2), 25),
    ],
)
def test_coastline_detail_per_region(name, box, floor):
    assert count_vertices(loader.load_layer("coast"), *box) >= floor, name


@pytest.mark.parametrize("name", ["land_lo", "coast_lo"])
def test_the_coarse_tier_still_has_the_small_islands(name):
    layer = loader.load_layer(name)
    for place, lat, lon in [
        ("Majuro", 7.1, 171.2),
        ("Midway", 28.2, -177.35),
        ("Tarawa", 1.45, 173.0),
        ("Wake Island", 19.3, 166.6),
        ("Dry Tortugas", 24.63, -82.87),
    ]:
        assert near(layer, lat, lon, 0.1), place


@pytest.mark.parametrize("name", loader.LAYERS)
def test_every_layer_parses_and_stays_inside_the_basin_box(name):
    layer = loader.load_layer(name)
    assert layer.paths
    assert layer.rings == name.startswith(("land", "lakes"))
    for path in layer.paths:
        assert len(path.points) >= (3 if layer.rings else 2)
        assert path.south == min(p[0] for p in path.points) and path.north == max(p[0] for p in path.points)
        assert path.west <= path.east
        for lat, lon in path.points:
            assert -10.0 <= lat <= 65.0  # the basin box plus its 5 degree margin
            assert 95.0 <= lon <= 180.0 or -180.0 <= lon <= -5.0


def test_layers_are_loaded_once():
    assert loader.load_layer("coast_lo") is loader.load_layer("coast_lo")


def test_the_detailed_data_is_more_detailed():
    assert loader.load_layer("coast").vertex_count > 3 * loader.load_layer("coast_lo").vertex_count
    assert loader.load_layer("land").vertex_count > 3 * loader.load_layer("land_lo").vertex_count


def test_no_stored_line_is_longer_than_the_piece_limit(build):
    assert max(len(p.points) for p in loader.load_layer("coast").paths) <= build.MAX_LINE_POINTS
    assert max(len(p.points) for p in loader.load_layer("borders").paths) <= build.MAX_LINE_POINTS


def test_the_great_lakes_are_there():
    lakes = loader.load_layer("lakes")
    assert near(lakes, 47.7, -87.5, 0.3)  # Superior
    assert near(lakes, 26.95, -80.8, 0.3)  # Okeechobee


def test_the_coast_is_where_it_should_be():
    coast = loader.load_layer("coast")
    for name, lat, lon in [
        ("Cape Canaveral", 28.46, -80.53),
        ("Cabo Catoche", 21.60, -87.05),
        ("Cape Hatteras", 35.25, -75.53),
        ("Cape San Antonio, Cuba", 21.87, -84.95),
        ("Punta Cana", 18.5, -68.4),
        ("Honolulu", 21.3, -157.85),
        ("Guam", 13.45, 144.75),
        ("Cabo San Lucas", 22.87, -109.9),
    ]:
        assert near(coast, lat, lon), name
    assert not near(coast, 25.0, -90.0, 0.5)  # open water in the middle of the Gulf


def test_land_polygons_cover_land_and_not_sea():
    land = loader.load_layer("land")

    def inside(lat, lon):
        crossings = 0
        for path in land.paths:
            if not (path.south <= lat <= path.north and path.west <= lon <= path.east):
                continue
            for (la, lo), (lb, ob) in zip(path.points, [*path.points[1:], path.points[0]], strict=True):
                if (la > lat) != (lb > lat) and lo + (lat - la) / (lb - la) * (ob - lo) > lon:
                    crossings += 1
        return crossings % 2 == 1

    assert inside(19.5, -89.0)  # the Yucatan
    assert inside(31.0, -84.0)  # south Georgia
    assert not inside(25.0, -90.0)  # the Gulf
    assert not inside(15.0, -70.0)  # the Caribbean


def test_borders_hold_countries_and_states():
    borders = loader.load_layer("borders")
    kinds = {path.kind for path in borders.paths}
    assert kinds == {loader.KIND_COUNTRY, loader.KIND_STATE}
    countries = loader.MapLayer(False, tuple(p for p in borders.paths if p.kind == loader.KIND_COUNTRY))
    states = loader.MapLayer(False, tuple(p for p in borders.paths if p.kind == loader.KIND_STATE))
    assert near(countries, 32.55, -117.1)  # the US and Mexico meet at the Pacific
    assert near(states, 31.0, -87.5)  # Alabama and Florida
    assert not near(countries, 31.0, -87.5, 0.1)


def test_unknown_layer_and_bad_data_are_rejected():
    with pytest.raises(ValueError, match="unknown map layer"):
        loader.load_layer("nope")
    with pytest.raises(ValueError, match="not an eyewall map data file"):
        loader.parse(struct.pack("<4sBBHII", b"XXXX", 2, 0, 0, 10_000, 0))
    with pytest.raises(ValueError):
        loader.parse(struct.pack("<4sBBHII", b"EWMD", 9, 0, 0, 10_000, 0))
    with pytest.raises(ValueError, match="truncated"):
        loader.parse(b"EWMD")
    with pytest.raises(ValueError, match="unit scale"):
        loader.parse(struct.pack("<4sBBHII", b"EWMD", 2, 0, 0, 0, 0))
    good = (DATA_DIR / "coast_lo.bin").read_bytes()
    for cut in (len(good) - 3, 20):
        with pytest.raises(ValueError, match="truncated"):
            loader.parse(good[:cut])


def test_the_attribution_page_matches_the_data(build):
    outputs = {f"{name}.bin": (DATA_DIR / f"{name}.bin").read_bytes() for name in (*loader.LAYERS, "places")}
    assert (DATA_DIR / "ATTRIBUTION.md").read_text(encoding="utf-8") == build.attribution(outputs)
    assert "public domain" in build.attribution(outputs)


# ------------------------------------------------------------------------------------------------ build functions

BOX = (0.0, 0.0, 10.0, 10.0)


def area(ring):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, [*ring[1:], ring[0]], strict=True))) / 2.0


def test_clipping_a_line_keeps_the_part_inside(build):
    assert build.clip_polyline([(-5, 5), (5, 5), (15, 5)], BOX) == [[(0.0, 5.0), (5, 5), (10.0, 5.0)]]
    assert build.clip_polyline([(1, 1), (2, 2), (3, 1)], BOX) == [[(1, 1), (2, 2), (3, 1)]]
    assert build.clip_polyline([(-5, -5), (-1, 20), (-3, 30)], BOX) == []


def test_a_line_that_leaves_and_returns_becomes_two_pieces(build):
    pieces = build.clip_polyline([(5, 5), (15, 5), (15, 8), (5, 8)], BOX)
    assert pieces == [[(5, 5), (10.0, 5.0)], [(10.0, 8.0), (5, 8)]]


def test_a_line_cutting_a_corner(build):
    assert build.clip_polyline([(-2, 8), (8, 18)], BOX) == []  # only touches the corner at (0, 10)
    assert build.clip_polyline([(-2, 6), (8, 16)], BOX) == [[(0.0, 8.0), (2.0, 10.0)]]


def test_clipping_a_ring(build):
    assert area(build.clip_ring([(5, 5), (15, 5), (15, 15), (5, 15)], BOX)) == pytest.approx(25.0)
    inside = [(2, 2), (4, 2), (3, 5)]
    assert build.clip_ring(inside, BOX) == inside
    assert build.clip_ring([(20, 20), (30, 20), (25, 30)], BOX) == []
    assert area(build.clip_ring([(-5, -5), (15, -5), (15, 15), (-5, 15)], BOX)) == pytest.approx(100.0)


def test_douglas_peucker_drops_what_is_within_tolerance(build):
    straight = [(0, 0), (1, 0.001), (2, -0.001), (3, 0)]
    assert build.simplify(straight, 0.01) == [(0, 0), (3, 0)]
    spike = [(0, 0), (1, 0), (1.5, 2), (2, 0), (3, 0)]
    assert (1.5, 2) in build.simplify(spike, 0.5)
    assert build.simplify([(0, 0), (1, 1)], 5) == [(0, 0), (1, 1)]
    assert build.simplify([(0, 0)], 5) == [(0, 0)]


def test_douglas_peucker_never_moves_a_point_farther_than_the_tolerance(build):
    wave = [(x / 10, math.sin(x / 7) * 0.5) for x in range(200)]
    tolerance = 0.05
    kept = build.simplify(wave, tolerance)
    assert kept[0] == wave[0] and kept[-1] == wave[-1] and len(kept) < len(wave) / 2
    for p in wave:
        assert min(build._segment_distance_squared(p, a, b) for a, b in itertools.pairwise(kept)) <= (
            tolerance**2 * 1.0001
        )


def test_a_ring_keeps_its_corners(build):
    ring = [(0, 0), (5, 0.001), (10, 0), (10, 5), (10, 10), (5, 10.001), (0, 10), (0, 5), (0, 0)]
    assert sorted(build.simplify_ring(ring, 0.05)) == [(0, 0), (0, 10), (10, 0), (10, 10)]


def test_quantize_rounds_to_ten_thousandths_and_drops_repeats(build):
    assert build.quantize([(1.00004, 2.00006), (1.000049, 2.000051), (-0.00015, 0.0)]) == [(10000, 20001), (-1, 0)]
    assert build.quantize([(-122.449999, 37.77549)]) == [(-1224500, 377755)]


def test_a_collinear_ring_has_no_area(build):
    result = build.simplify_ring([(0, 0), (1, 0), (2, 0), (3, 0)], 0.01)
    assert len(result) <= 3 and area(result) == 0


def test_a_tiny_ring_survives_simplification_as_a_triangle(build):
    islet = [(0, 0), (0.001, 0), (0.001, 0.001), (0.0005, 0.0015), (0, 0.001), (0, 0)]
    assert len(build.simplify_ring(islet, 0.03)) == 3


def test_a_big_ring_is_cut_into_tiles_that_cover_it_exactly(build):
    ring = [(0.0, 0.0), (23.0, 0.0), (23.0, 4.0), (12.0, 2.0), (0.0, 4.0)]
    pieces = build.tile_ring(ring, (0.0, 0.0, 30.0, 10.0))
    assert len(pieces) > 3
    assert sum(area(piece) for piece in pieces) == pytest.approx(area(ring))
    assert all(max(p[0] for p in piece) - min(p[0] for p in piece) <= build.TILE + 1e-9 for piece in pieces)


def test_a_long_line_is_split_with_one_shared_vertex(build):
    points = [(i, i % 7) for i in range(1000)]
    parts = build.split_line(points)
    assert all(len(part) <= build.MAX_LINE_POINTS for part in parts)
    assert all(a[-1] == b[0] for a, b in itertools.pairwise(parts))
    assert [p for part in parts for p in part[:-1]] + [parts[-1][-1]] == points


def test_the_encoding_round_trips_through_the_loader(build):
    paths = [
        (0, [(-800000, 250000), (-799900, 250100), (1800000, -50000)]),
        (1, [(10000, 100), (10100, 200), (10050, 300)]),
    ]
    for rings in (False, True):
        data = build.pack(paths, rings=rings)
        assert build.unpack(data) == (rings, paths)
        layer = loader.parse(data)
        assert layer.rings is rings
        assert layer.paths[0].points == ((25.0, -80.0), (25.01, -79.99), (-5.0, 180.0))
        assert layer.paths[1].kind == 1
        assert (layer.paths[0].south, layer.paths[0].west, layer.paths[0].north, layer.paths[0].east) == (
            -5.0, -80.0, 25.01, 180.0)  # fmt: skip


def geojson(*geometries):
    return json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": g}
                                                                 for g in geometries]})  # fmt: skip


def line(*points):
    return {"type": "LineString", "coordinates": [list(p) for p in points]}


def polygon(*rings):
    return {"type": "Polygon", "coordinates": [[list(p) for p in ring] for ring in rings]}


def test_convert_splits_at_the_basin_box_and_keeps_both_sides_of_the_antimeridian(build):
    geometries = [
        (line((90, 10), (110, 10), (150, 12), (179.9, 12)), 0),  # starts west of the box
        (line((-179.9, 12), (-120, 12), (0, 12)), 0),  # ends east of the box
        (line((0, 0), (5, 5)), 0),  # entirely outside
    ]
    paths = build.convert(geometries, rings=False, tolerance=0.01)
    assert len(paths) == 2
    assert paths[0][1][0] == (950000, 100000)  # clipped at 95 E, the 5 degree margin west of 100 E
    assert paths[1][1][-1] == (-50000, 120000)  # clipped at 5 W, the 5 degree margin east of 10 W


def test_convert_rings_and_holes(build):
    outer = [(120, 10), (130, 10), (130, 20), (120, 20), (120, 10)]
    hole = [(123, 13), (127, 13), (127, 17), (123, 17), (123, 13)]
    far = [(0, 10), (5, 10), (5, 20), (0, 10)]
    paths = build.convert([(polygon(outer, hole), 0), (polygon(far), 0)], rings=True, tolerance=0.01, tile=False)
    assert len(paths) == 2  # the outer ring and the hole; the distant island is dropped
    assert {len(points) for _, points in paths} == {4}
    assert all(points[0] != points[-1] for _, points in paths)  # rings are closed implicitly
    tiled = build.convert([(polygon(outer, hole), 0)], rings=True, tolerance=0.01)
    assert len(tiled) > 2  # a 10 degree ring is cut along the 5 degree grid


def write_sources(directory: Path) -> None:
    sources = {
        "ne_10m_coastline": line((105, 5), (120, 6), (125, 9)),
        "ne_10m_minor_islands_coastline": line((105, 5), (125, 9)),
        "ne_10m_land": polygon([(120, 10), (130, 10), (130, 20), (120, 20), (120, 10)]),
        "ne_10m_lakes": polygon([(-80, 10), (-70, 10), (-70, 20), (-80, 20), (-80, 10)]),
        "ne_10m_admin_0_boundary_lines_land": line((-100, 30), (-90, 31)),
        "ne_10m_admin_1_states_provinces_lines": line((-95, 30), (-92, 33)),
    }
    directory.mkdir(parents=True, exist_ok=True)
    for name, geometry in sources.items():
        (directory / f"{name}.geojson").write_text(geojson(geometry), encoding="utf-8")
    (directory / "ne_10m_populated_places_simple.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-80.2, 25.8]},
                        "properties": {
                            "name": "Miami",
                            "nameascii": "Miami",
                            "scalerank": 1,
                            "pop_max": 5000000,
                            "latitude": 25.8,
                            "longitude": -80.2,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def offline(build, monkeypatch, tmp_path):
    """The build script pointed at a tiny fake download folder, with the network made unreachable."""

    def no_network(*args, **kwargs):
        raise AssertionError("the build must not download anything in tests")

    monkeypatch.setattr(build.urllib.request, "urlopen", no_network)
    write_sources(tmp_path / "cache")
    digests = {
        name: hashlib.sha256((tmp_path / "cache" / f"{name}.geojson").read_bytes()).hexdigest()
        for name in build.SOURCE_SHA256
    }
    monkeypatch.setattr(build, "SOURCE_SHA256", digests)
    return tmp_path


def test_the_build_is_reproducible(build, offline):
    first = build.build(offline / "cache")
    second = build.build(offline / "cache")
    assert first == second
    assert set(first) == {f"{name}.bin" for name in loader.LAYERS} | {"places.bin", "ATTRIBUTION.md"}
    assert loader.parse(first["borders.bin"]).paths[0].kind == loader.KIND_COUNTRY
    assert {p.kind for p in loader.parse(first["borders.bin"]).paths} == {0, 1}
    assert [p.name for p in loader.parse_places(first["places.bin"])] == ["Miami"]


def test_main_writes_the_files_and_check_notices_drift(build, offline, capsys):
    args = ["--cache", str(offline / "cache"), "--out", str(offline / "out")]
    assert build.main(args) == 0
    assert (offline / "out" / "coast.bin").exists() and (offline / "out" / "ATTRIBUTION.md").exists()
    assert build.main([*args, "--check"]) == 0
    (offline / "out" / "land.bin").write_bytes(b"changed")
    assert build.main([*args, "--check"]) == 1
    assert "land.bin" in capsys.readouterr().err


def test_a_download_that_does_not_match_its_hash_is_refused(build, offline, monkeypatch):
    monkeypatch.setattr(build, "SOURCE_SHA256", {**build.SOURCE_SHA256, "ne_10m_coastline": "0" * 64})
    with pytest.raises(SystemExit, match="expected 0000"):
        build.build(offline / "cache")
